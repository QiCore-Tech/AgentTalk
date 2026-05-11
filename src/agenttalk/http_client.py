from __future__ import annotations

import os
import time
from collections.abc import Collection, Mapping
from typing import Any

import httpx


DEFAULT_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_STATUSES = frozenset({502, 503, 504})
DEFAULT_STATUS_RETRY_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})


class HubRequestError(RuntimeError):
    pass


class HubConnectionError(HubRequestError):
    def __init__(self, *, method: str, url: str, attempts: int, cause: Exception) -> None:
        self.method = method.upper()
        self.url = url
        self.attempts = attempts
        self.cause = cause
        super().__init__(
            f"Hub connection failed after {attempts} attempt(s): "
            f"{self.method} {url} ({type(cause).__name__}: {cause})"
        )


class HubStatusError(HubRequestError):
    def __init__(self, *, method: str, url: str, status_code: int, attempts: int) -> None:
        self.method = method.upper()
        self.url = url
        self.status_code = status_code
        self.attempts = attempts
        super().__init__(
            f"Hub returned HTTP {status_code} after {attempts} attempt(s): "
            f"{self.method} {url}"
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
    retry_statuses: Collection[int] | None = None,
) -> httpx.Response:
    """Run a Hub HTTP request with bounded retries for connection setup errors.

    The production failure mode we have seen is TLS handshake EOF from the
    Hub/proxy. That surfaces as ``httpx.ConnectError`` before the request body is
    accepted by the server, so a short retry is safe even for POST calls.
    Response read failures are deliberately not retried here because a write may
    already have reached the Hub.
    """

    resolved_method = method.upper()
    max_attempts = _resolved_attempts(attempts)
    statuses_to_retry = _resolved_retry_statuses(resolved_method, retry_statuses)
    last_error: Exception | None = None
    for attempt_index in range(max_attempts):
        try:
            response = httpx.request(
                method,
                url,
                headers=dict(headers or {}),
                params=params,
                json=json,
                timeout=timeout,
            )
            if response.status_code in statuses_to_retry:
                if attempt_index + 1 >= max_attempts:
                    raise HubStatusError(
                        method=resolved_method,
                        url=url,
                        status_code=response.status_code,
                        attempts=max_attempts,
                    )
                time.sleep(_retry_delay(attempt_index))
                continue
            return response
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


def _resolved_retry_statuses(method: str, retry_statuses: Collection[int] | None) -> frozenset[int]:
    if retry_statuses is not None:
        return frozenset(retry_statuses)
    if method in DEFAULT_STATUS_RETRY_METHODS:
        return DEFAULT_RETRY_STATUSES
    return frozenset()


def _retry_delay(attempt_index: int) -> float:
    # Keep CLI latency low while still riding out a transient proxy/TLS reset.
    return min(0.25 * (2**attempt_index), 1.0)
