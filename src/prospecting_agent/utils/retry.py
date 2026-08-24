"""Shared retry/backoff policy for flaky external API calls (Places, OpenAI, Sheets)."""

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


def with_retry(exception_types: tuple[type[Exception], ...] = (Exception,), attempts: int = 3):
    """Exponential backoff retry decorator: up to `attempts` tries, 1s/2s/4s waits by default.

    Only retries the given exception types (transient/network errors) — logic errors and
    validation failures should propagate immediately, not be retried.

    Usage:
        @with_retry((TimeoutError, ConnectionError))
        def call_api(): ...
    """
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(exception_types),
        reraise=True,
    )
