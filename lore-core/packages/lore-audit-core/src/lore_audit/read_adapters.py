"""Concrete capability-confined table, image, and current-source readers."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from lore_audit.read import (
    Availability,
    ImageDelivery,
    ImageDeliveryKind,
    ImageRequest,
    SensitiveValue,
    SourceContext,
    SourceContextRequest,
    SourceHashState,
    TableFilter,
    TablePageRequest,
    TableProfile,
    TableProfileRequest,
    TableRowPage,
    TableSampleRequest,
)
from lore_audit.image_safety import (
    validate_safe_raster_content_type,
    validate_safe_raster_payload,
)
from lore_audit.postgres_connections import acquire_postgres_connection
from lore_audit.read_cursor import CursorCodec
from lore_audit.repository import (
    RegisteredPayloadToken,
    RegisteredSourceToken,
)

_TABLE_ERROR = "invalid registered table capability"
_IMAGE_ERROR = "invalid registered image capability"
_SOURCE_ERROR = "invalid current source capability"
_ROW_NUMBER = "_splitter_row_number"


def _json_safe_table_cell(value: Any) -> Any:
    if type(value) is Decimal:
        return str(value)
    if type(value) is date:
        return value.isoformat()
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise ValueError(_TABLE_ERROR)


class PostgresRegisteredTableReader:
    """Read only allowlisted columns from one validated registered table token."""

    def __init__(self, connection: Any, cursor_codec: CursorCodec) -> None:
        self._connection = connection
        self._cursor_codec = cursor_codec

    @staticmethod
    def _registration(token: RegisteredPayloadToken) -> tuple[str, str, tuple[str, ...], int]:
        if token.storage_kind != "postgres" or not isinstance(token.identity, Mapping):
            raise ValueError(_TABLE_ERROR)
        if set(token.identity) != {"schema_name", "table_name"}:
            raise ValueError(_TABLE_ERROR)
        schema = token.identity.get("schema_name")
        table = token.identity.get("table_name")
        registration = token.registration
        if not isinstance(schema, str) or not schema or not isinstance(table, str) or not table:
            raise ValueError(_TABLE_ERROR)
        if not isinstance(registration, Mapping):
            raise ValueError(_TABLE_ERROR)
        columns = registration.get("columns")
        row_count = registration.get("row_count")
        if (
            not isinstance(columns, (list, tuple))
            or not columns
            or any(not isinstance(item, str) or not item for item in columns)
            or len(columns) != len(set(columns))
            or type(row_count) is not int
            or row_count < 0
        ):
            raise ValueError(_TABLE_ERROR)
        if registration.get("schema_name") != schema or registration.get("table_name") != table:
            raise ValueError(_TABLE_ERROR)
        return schema, table, tuple(columns), row_count

    def get_profile(
        self, token: RegisteredPayloadToken, request: TableProfileRequest
    ) -> TableProfile:
        if not isinstance(request, TableProfileRequest):
            raise ValueError(_TABLE_ERROR)
        _, _, columns, row_count = self._registration(token)
        return TableProfile(
            request.payload_id,
            columns,
            row_count,
            {"column_count": len(columns)},
        )

    def get_page(
        self, token: RegisteredPayloadToken, request: TablePageRequest
    ) -> TableRowPage:
        if not isinstance(request, TablePageRequest):
            raise ValueError(_TABLE_ERROR)
        schema, table, registered, _ = self._registration(token)
        self._validate_columns(request, registered)
        return self._query_page(schema, table, request)

    def get_sample(
        self, token: RegisteredPayloadToken, request: TableSampleRequest
    ) -> TableRowPage:
        if not isinstance(request, TableSampleRequest):
            raise ValueError(_TABLE_ERROR)
        schema, table, registered, _ = self._registration(token)
        if any(column not in registered for column in request.columns):
            raise ValueError(_TABLE_ERROR)
        page_request = TablePageRequest(
            request.run_id,
            request.payload_id,
            request.columns,
            bounds=replace(request.bounds, page_size=request.limit),
        )
        return self._query_page(schema, table, page_request, operation="table_sample")

    @staticmethod
    def _validate_columns(request: TablePageRequest, registered: tuple[str, ...]) -> None:
        allowed = set(registered)
        if (
            any(column not in allowed for column in request.columns)
            or (request.sort_column is not None and request.sort_column not in allowed)
            or any(item.column not in allowed for item in request.filters)
        ):
            raise ValueError(_TABLE_ERROR)

    def _query_page(
        self,
        schema: str,
        table: str,
        request: TablePageRequest,
        *,
        operation: str = "table_page",
    ) -> TableRowPage:
        sql = importlib.import_module("psycopg").sql
        sort_column = request.sort_column or _ROW_NUMBER
        direction = "DESC" if request.descending else "ASC"
        sort_name = (
            f"{sort_column},{_ROW_NUMBER}:{direction.lower()}"
            if sort_column == _ROW_NUMBER
            else f"{sort_column}:{direction.lower()}:nulls_last,"
            f"{_ROW_NUMBER}:{direction.lower()}"
        )
        filter_projection = {
            "run_id": request.run_id,
            "payload_id": request.payload_id,
            "columns": list(request.columns),
            "filters": [
                {"column": item.column, "operator": item.operator, "values": list(item.values)}
                for item in request.filters
            ],
            "page_size": request.bounds.page_size,
        }
        last = None
        if request.cursor:
            last = self._cursor_codec.decode_page(
                request.cursor,
                operation=operation,
                sort=sort_name,
                filters=filter_projection,
            )
            expected_length = 1 if sort_column == _ROW_NUMBER else 3
            if len(last) != expected_length:
                raise ValueError(_TABLE_ERROR)
            if sort_column != _ROW_NUMBER and (
                type(last[0]) is not bool
                or type(last[2]) is not int
                or (last[0] and last[1] is not None)
                or (not last[0] and last[1] is None)
            ):
                raise ValueError(_TABLE_ERROR)

        predicates: list[Any] = []
        params: list[Any] = []
        for item in request.filters:
            clause, values = self._filter_clause(sql, item)
            predicates.append(clause)
            params.extend(values)
        if last:
            comparator = sql.SQL("<") if request.descending else sql.SQL(">")
            if sort_column == _ROW_NUMBER:
                predicates.append(
                    sql.SQL("{} {} %s").format(sql.Identifier(_ROW_NUMBER), comparator)
                )
                params.append(last[0])
            elif last[0]:
                predicates.append(
                    sql.SQL("({} IS NULL AND {} {} %s)").format(
                        sql.Identifier(sort_column),
                        sql.Identifier(_ROW_NUMBER),
                        comparator,
                    )
                )
                params.append(last[2])
            else:
                predicates.append(
                    sql.SQL(
                        "(({} IS NOT NULL AND ({}, {}) {} (%s, %s)) OR {} IS NULL)"
                    ).format(
                        sql.Identifier(sort_column),
                        sql.Identifier(sort_column),
                        sql.Identifier(_ROW_NUMBER),
                        comparator,
                        sql.Identifier(sort_column),
                    )
                )
                params.extend(last[1:])

        selected = [sql.Identifier(column) for column in request.columns]
        if sort_column == _ROW_NUMBER:
            selected.append(sql.Identifier(_ROW_NUMBER))
        else:
            selected.extend(
                (
                    sql.SQL("{} IS NULL").format(sql.Identifier(sort_column)),
                    sql.Identifier(sort_column),
                    sql.Identifier(_ROW_NUMBER),
                )
            )
        statement = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(", ").join(selected),
            sql.Identifier(schema),
            sql.Identifier(table),
        )
        if predicates:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(predicates)
        if sort_column == _ROW_NUMBER:
            order_parts = [
                sql.SQL("{} {}").format(sql.Identifier(_ROW_NUMBER), sql.SQL(direction))
            ]
        else:
            # Both directions put NULL last; cursor flag/value/row mirrors this exact order.
            order_parts = [
                sql.SQL("{} IS NULL ASC").format(sql.Identifier(sort_column)),
                sql.SQL("{} {}").format(sql.Identifier(sort_column), sql.SQL(direction)),
                sql.SQL("{} {}").format(sql.Identifier(_ROW_NUMBER), sql.SQL(direction)),
            ]
        statement += sql.SQL(" ORDER BY {} LIMIT %s").format(sql.SQL(", ").join(order_parts))
        params.append(request.bounds.page_size + 1)

        with acquire_postgres_connection(self._connection) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{request.bounds.timeout_ms}ms",),
                )
                cursor.execute(statement, tuple(params))
                values = tuple(cursor.fetchall())
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

        truncated = len(values) > request.bounds.page_size
        chosen = values[: request.bounds.page_size]
        output_size = len(request.columns)
        rows = tuple(
            {
                column: _json_safe_table_cell(value)
                for column, value in zip(
                    request.columns, row[:output_size], strict=True
                )
            }
            for row in chosen
        )
        if len(json.dumps(rows).encode("utf-8")) > request.bounds.max_text_bytes:
            raise ValueError(_TABLE_ERROR)
        next_cursor = None
        if truncated:
            final = chosen[-1]
            last_value = (final[-1],) if sort_column == _ROW_NUMBER else final[-3:]
            next_cursor = self._cursor_codec.encode_page(
                operation=operation,
                sort=sort_name,
                filters=filter_projection,
                last=last_value,
            )
        return TableRowPage(
            request.payload_id,
            request.columns,
            rows,
            next_cursor,
            truncated,
        )

    @staticmethod
    def _filter_clause(sql: Any, item: TableFilter) -> tuple[Any, tuple[Any, ...]]:
        column = sql.Identifier(item.column)
        if item.operator == "is_null":
            return sql.SQL("{} IS NULL").format(column), ()
        value = item.values[0]
        operators = {
            "eq": "=",
            "ne": "<>",
            "lt": "<",
            "lte": "<=",
            "gt": ">",
            "gte": ">=",
        }
        if item.operator in operators:
            return sql.SQL("{} {} %s").format(column, sql.SQL(operators[item.operator])), (value,)
        if not isinstance(value, str):
            raise ValueError(_TABLE_ERROR)
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"{escaped}%" if item.operator == "prefix" else f"%{escaped}%"
        return sql.SQL("{} LIKE %s ESCAPE E'\\\\'").format(column), (pattern,)


class S3RegisteredImageReader:
    """Return verified inline bytes or a short-lived link for one registered object."""

    def __init__(
        self,
        hook: Any,
        *,
        inline_cap_bytes: int = 1_000_000,
        link_expiry_seconds: int = 300,
    ) -> None:
        if (
            hook is None
            or type(inline_cap_bytes) is not int
            or inline_cap_bytes <= 0
            or type(link_expiry_seconds) is not int
            or not 0 < link_expiry_seconds <= 3600
        ):
            raise ValueError(_IMAGE_ERROR)
        self._hook = hook
        self._inline_cap_bytes = inline_cap_bytes
        self._link_expiry_seconds = link_expiry_seconds

    @staticmethod
    def _identity(token: RegisteredPayloadToken) -> tuple[str, str]:
        if token.storage_kind != "s3" or not isinstance(token.identity, Mapping):
            raise ValueError(_IMAGE_ERROR)
        if set(token.identity) != {"bucket", "object_key"}:
            raise ValueError(_IMAGE_ERROR)
        bucket = token.identity.get("bucket")
        key = token.identity.get("object_key")
        if (
            not isinstance(bucket, str)
            or not bucket
            or not isinstance(key, str)
            or not key
            or token.byte_size is None
            or token.byte_size < 0
            or not token.checksum_sha256
            or not token.content_type
        ):
            raise ValueError(_IMAGE_ERROR)
        try:
            validate_safe_raster_content_type(token.content_type)
        except ValueError:
            raise ValueError(_IMAGE_ERROR) from None
        return bucket, key

    def get_image(self, token: RegisteredPayloadToken, request: ImageRequest) -> ImageDelivery:
        if not isinstance(request, ImageRequest):
            raise ValueError(_IMAGE_ERROR)
        bucket, key = self._identity(token)
        if request.prefer_inline and token.byte_size <= min(
            self._inline_cap_bytes, request.bounds.max_text_bytes
        ):
            payload = self._read_bytes(bucket, key)
            if (
                not isinstance(payload, bytes)
                or len(payload) != token.byte_size
                or hashlib.sha256(payload).hexdigest() != token.checksum_sha256
            ):
                raise ValueError(_IMAGE_ERROR)
            try:
                validate_safe_raster_payload(token.content_type, payload)
            except ValueError:
                raise ValueError(_IMAGE_ERROR) from None
            return ImageDelivery(
                request.payload_id,
                Availability.AVAILABLE,
                ImageDeliveryKind.INLINE_PREVIEW,
                token.content_type,
                token.byte_size,
                token.checksum_sha256,
                SensitiveValue(payload),
            )
        url = self._hook.generate_presigned_url(
            client_method="get_object",
            params={"Bucket": bucket, "Key": key},
            expires_in=self._link_expiry_seconds,
        )
        if not isinstance(url, str) or not url:
            raise ValueError(_IMAGE_ERROR)
        return ImageDelivery(
            request.payload_id,
            Availability.AVAILABLE,
            ImageDeliveryKind.TEMPORARY_LINK,
            token.content_type,
            token.byte_size,
            token.checksum_sha256,
            SensitiveValue(url),
            datetime.now(UTC) + timedelta(seconds=self._link_expiry_seconds),
        )

    def _read_bytes(self, bucket: str, key: str) -> bytes:
        if hasattr(self._hook, "get_bytes"):
            return self._hook.get_bytes(key=key, bucket_name=bucket)
        object_handle = self._hook.get_key(key=key, bucket_name=bucket)
        response = object_handle.get()
        return response["Body"].read()


class CurrentSourceObjectReader:
    """Hash only the current object returned by an injected confined loader."""

    def __init__(self, loader: Callable[..., bytes]) -> None:
        if not callable(loader):
            raise ValueError(_SOURCE_ERROR)
        self._loader = loader

    def get_source_context(
        self, token: RegisteredSourceToken, request: SourceContextRequest
    ) -> SourceContext:
        if (
            not isinstance(token, RegisteredSourceToken)
            or not isinstance(request, SourceContextRequest)
            or token.run_id != request.run_id
        ):
            raise ValueError(_SOURCE_ERROR)
        payload = self._loader(
            token.identity,
            max_bytes=request.bounds.max_text_bytes,
            timeout_ms=request.bounds.timeout_ms,
        )
        if not isinstance(payload, bytes) or len(payload) > request.bounds.max_text_bytes:
            raise ValueError(_SOURCE_ERROR)
        current_hash = hashlib.sha256(payload).hexdigest()
        state = (
            SourceHashState.MATCH
            if current_hash == token.expected_hash
            else SourceHashState.MISMATCH
        )
        return SourceContext(
            request.run_id,
            state,
            Availability.AVAILABLE,
            token.expected_hash,
            current_hash,
        )


__all__ = [
    "CurrentSourceObjectReader",
    "PostgresRegisteredTableReader",
    "S3RegisteredImageReader",
]
