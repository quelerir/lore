"""Transport-independent bounded structured-model retry policy."""
# ruff: noqa: E501, UP035

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

MODEL_IDS = {"standard": "qwen/qwen3.6-plus", "economy": "openai/gpt-oss-120b"}


class StructuredClient(Protocol):
    def request(
        self, rendered_request: str, *, model_id: str, per_call_timeout_seconds: float
    ) -> Any: ...


class RetryableLLMError(Exception):
    pass


class FatalLLMError(Exception):
    pass


@dataclass(frozen=True)
class BatchLLMConfig:
    tier: str = "standard"
    per_call_timeout_seconds: float = 60
    batch_timeout_seconds: float = 300
    max_retries: int = 5
    retry_delay_seconds: float = 1

    def __post_init__(self) -> None:
        if (
            self.tier not in MODEL_IDS
            or self.per_call_timeout_seconds <= 0
            or self.batch_timeout_seconds <= 0
        ):
            raise ValueError("invalid_llm_configuration")
        if not 0 <= self.max_retries <= 5:
            raise ValueError("invalid_retry_limit")

    @property
    def model_id(self) -> str:
        return MODEL_IDS[self.tier]


@dataclass(frozen=True)
class BatchFailure:
    batch_ordinal: int
    slot_start: str
    slot_end: str
    attempts: int
    model_id: str
    error_code: str


@dataclass(frozen=True)
class BatchOutcome:
    envelope: Any = None
    failure: BatchFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


def run_batch(
    client: StructuredClient,
    request: Any,
    *,
    config: BatchLLMConfig | None = None,
    validate: Callable[[Any, Any], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> BatchOutcome:
    active = config or BatchLLMConfig()
    started = clock()
    attempts = 0
    while attempts <= active.max_retries:
        if clock() - started >= active.batch_timeout_seconds:
            return BatchOutcome(failure=_failure(request, attempts, active, "LLM-BATCH-TIMEOUT"))
        attempts += 1
        try:
            envelope = client.request(
                request.rendered_request,
                model_id=active.model_id,
                per_call_timeout_seconds=active.per_call_timeout_seconds,
            )
            if validate is not None:
                envelope = validate(envelope, request)
            return BatchOutcome(envelope=envelope)
        except FatalLLMError:
            return BatchOutcome(failure=_failure(request, attempts, active, "LLM-FATAL"))
        except (RetryableLLMError, ValueError):
            if attempts > active.max_retries:
                return BatchOutcome(
                    failure=_failure(request, attempts, active, "LLM-RETRY-EXHAUSTED")
                )
            delay = min(
                active.retry_delay_seconds * (2 ** (attempts - 1)), active.batch_timeout_seconds
            )
            if clock() - started + delay >= active.batch_timeout_seconds:
                return BatchOutcome(
                    failure=_failure(request, attempts, active, "LLM-BATCH-TIMEOUT")
                )
            sleep(delay)
    return BatchOutcome(failure=_failure(request, attempts, active, "LLM-RETRY-EXHAUSTED"))


def _failure(request: Any, attempts: int, config: BatchLLMConfig, code: str) -> BatchFailure:
    return BatchFailure(
        request.ordinal, request.slot_start, request.slot_end, attempts, config.model_id, code
    )
