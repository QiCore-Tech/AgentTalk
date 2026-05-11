from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

import httpx


DEFAULT_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 10.0


class HubConnectionError(RuntimeError):
    def __init__(self, *, method: str, url: str, attempts: int, cause: Exception) -> None:
        self.method = method.upper()
        self.url = url
        self.attempts = attempts
        self.cause = cause
        super().__init__(
            f"Hub connection failed after {attempts} attempt(s): "
            f"{self.method} {url} ({type(cause).__name__}: {cause})"
        )


def request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    json: Any | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int | None = None,
) -> httpx.Response:
    """Run a Hub HTTP request with bounded retries for connection setup errors.

    The production failure mode we have seen is TLS handshake EOF from the
    Hub/proxy. That surfaces as ``httpx.ConnectError`` before the request body is
    accepted by the server, so a short retry is safe even for POST calls.
    Response read failures are deliberately not retried here because a write may
    already have reached the Hub.
    """

    max_attempts = _resolved_attempts(attempts)
    last_error: Exception | None = None
    for attempt_index in range(max_attempts):
        try:
            return httpx.request(
                method,
                url,
                headers=dict(headers or {}),
                params=params,
                json=json,
                timeout=timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
            if attempt_index + 1 >= max_attempts:
                break
            time.sleep(_retry_delay(attempt_index))
        except httpx.TransportError as exc:
            # Do not retry read/write failures: the request may have reached the
            # Hub already. Still turn the low-level traceback into a concise
            # operator-facing error.
            raise HubConnectionError(
                method=method,
                url=url,
                attempts=attempt_index + 1,
                cause=exc,
            ) from exc
    assert last_error is not None
    raise HubConnectionError(method=method, url=url, attempts=max_attempts, cause=last_error) from last_error


def _resolved_attempts(attempts: int | None) -> int:
    if attempts is not None:
        return max(1, attempts)
    raw = os.environ.get("AGENTTALK_HTTP_ATTEMPTS", "").strip()
    if not raw:
        return DEFAULT_ATTEMPTS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_ATTEMPTS


def _retry_delay(attempt_index: int) -> float:
    # Keep CLI latency low while still riding out a transient proxy/TLS reset.
    return min(0.25 * (2**attempt_index), 1.0)
