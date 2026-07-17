"""Регресс: соединение НЕ шлёт startup-параметры (их рвёт transaction-pooling
пулер), read-only и statement_timeout навешиваются ПО-ТРАНЗАКЦИОННО, а само
соединение гарантированно закрывается. Плюс контракт run_select: LIMIT-обёртка,
таймаут и ошибка БД как строка, а не исключение. Живая БД не нужна."""

import asyncio

import asyncpg

from toast.models import DbError


LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


def _run(coro):
    return asyncio.run(coro)


class _FakeTxn:
    def __init__(self, conn, readonly):
        conn.readonly_flags.append(readonly)

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, fetch_error: Exception | None = None):
        self.readonly_flags: list[bool] = []
        self.executed: list[str] = []
        self.fetched: list[str] = []
        self.closed = False
        self._fetch_error = fetch_error

    def transaction(self, readonly=False):
        return _FakeTxn(self, readonly)

    async def execute(self, query, *args):
        self.executed.append(query)

    async def fetch(self, query, *args):
        self.fetched.append(query)
        if self._fetch_error is not None:
            raise self._fetch_error
        return []

    async def close(self):
        self.closed = True


def _patch(monkeypatch, fetch_error: Exception | None = None):
    import toast.executor as ex

    conn = _FakeConn(fetch_error)
    captured: dict = {}

    async def fake_connect(dsn, **kwargs):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return conn

    monkeypatch.setattr(ex.asyncpg, "connect", fake_connect)
    return ex, conn, captured


def _select(ex, conn_unused=None):
    e = ex.PgExecutor("postgresql://u:p@pooler:6543/db")
    return e.run_select(f"SELECT column_1 FROM splitter_toast.{LEGAL}", LEGAL)


def test_connect_has_no_startup_params(monkeypatch):
    ex, conn, captured = _patch(monkeypatch)
    _run(_select(ex))
    # Ровно причина падения за пулером: startup-параметры соединения.
    assert "server_settings" not in captured
    # prepared statements ломаются за transaction-pooling пулером
    assert captured.get("statement_cache_size") == 0
    # read-only и timeout — внутри транзакции; соединение закрыто.
    assert conn.readonly_flags == [True]
    assert any("statement_timeout" in q for q in conn.executed)
    assert conn.closed


def test_run_select_wraps_query_with_limit(monkeypatch):
    # Усечение на стороне БД: наружу уходит обёртка LIMIT MAX_ROWS+1.
    ex, conn, _ = _patch(monkeypatch)
    _run(_select(ex))
    assert len(conn.fetched) == 1
    assert conn.fetched[0].startswith("SELECT * FROM (")
    assert conn.fetched[0].endswith(f"LIMIT {ex.MAX_ROWS + 1}")
    assert f"splitter_toast.{LEGAL}" in conn.fetched[0]


def test_client_timeout_returns_error_string(monkeypatch):
    # command_timeout asyncpg — клиентский TimeoutError, не PostgresError;
    # он не должен пробрасываться и ронять граф.
    ex, conn, _ = _patch(monkeypatch, fetch_error=TimeoutError())
    res = _run(_select(ex))
    assert isinstance(res, DbError) and "таймаут" in res.message
    assert conn.closed


def test_postgres_error_returns_error_string(monkeypatch):
    ex, conn, _ = _patch(
        monkeypatch, fetch_error=asyncpg.PostgresSyntaxError("bad syntax")
    )
    res = _run(_select(ex))
    assert isinstance(res, DbError) and res.message.startswith("Ошибка SQL:")
    assert conn.closed


def test_plain_bytes_decoded_not_json_parsed():
    from toast.executor import _plain

    assert _plain(b"\xd0\xb0\xff") == "а�"
    assert _plain("s") == "s"
    assert _plain(None) is None
    assert _plain(3.5) == 3.5
