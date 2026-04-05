from __future__ import annotations

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import httpx
import logging

logger = logging.getLogger(__name__)

# Standard retry for external HTTP tool calls:
# 3 attempts, exponential backoff 2s -> 4s -> 8s (max 10s)
http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        httpx.NetworkError,
        httpx.TimeoutException,
        httpx.HTTPStatusError,
    )),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

# Lighter retry for fast internal calls (2 attempts, 1s backoff)
quick_retry = retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((
        httpx.NetworkError,
        httpx.TimeoutException,
    )),
    reraise=True,
)
