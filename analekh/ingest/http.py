"""Polite HTTP client: descriptive User-Agent, timeouts, rate limit, exponential backoff (9.2-9.3).

Design rule (section 3.2): only published RSS feeds, the equity list CSVs and the files the feeds
link to. Never NSE's internal JSON endpoints or crawled pages: the host allow-list enforces it.
"""

import threading
import time
from dataclasses import dataclass

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from analekh.config import get_settings

ALLOWED_HOSTS = {
    "nsearchives.nseindia.com",
    "archives.nseindia.com",
}

RETRY_STATUSES = {429, 500, 502, 503, 504}


class DisallowedHostError(ValueError):
    pass


@dataclass
class FetchResult:
    status: int
    content: bytes
    etag: str | None
    last_modified: str | None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class RateLimiter:
    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in RETRY_STATUSES


class PoliteClient:
    def __init__(
        self,
        extra_allowed_hosts: set[str] | None = None,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 4,
        backoff_base: float = 2.0,
    ) -> None:
        s = get_settings()
        self.allowed = ALLOWED_HOSTS | (extra_allowed_hosts or set())
        self.limiter = RateLimiter(s.download_rate_per_second)
        self.client = httpx.Client(
            headers={"User-Agent": s.user_agent, "Accept": "*/*"},
            timeout=s.http_timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )
        self._get = retry(
            retry=retry_if_exception(_retryable),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=backoff_base, max=60),
            reraise=True,
        )(self._get_once)

    def get(
        self, url: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        host = httpx.URL(url).host
        if host not in self.allowed:
            raise DisallowedHostError(f"{host} is not an allowed source host")
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        result: FetchResult = self._get(url, headers)
        return result

    def _get_once(self, url: str, headers: dict[str, str]) -> FetchResult:
        self.limiter.wait()
        resp = self.client.get(url, headers=headers)
        if resp.status_code != 304:
            resp.raise_for_status()
        return FetchResult(
            resp.status_code,
            resp.content,
            resp.headers.get("ETag"),
            resp.headers.get("Last-Modified"),
        )
