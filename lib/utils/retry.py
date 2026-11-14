from __future__ import annotations

import asyncio
import functools
import time
from typing import Callable

from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("retry")


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_backoff: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator for async functions with retry logic and exponential backoff.

    Args:
        max_attempts: Total number of attempts before raising the last exception.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound on the computed delay between retries.
        exponential_backoff: If True, doubles the delay on each attempt.
        exceptions: Tuple of exception types that trigger a retry.

    Returns:
        A decorator that wraps the target coroutine with retry behaviour.
    """

    def decorator(func: Callable) -> Callable:
        """Wrap an async function with the configured retry behaviour."""

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}: {e}")
                        raise
                    delay = min(
                        base_delay * (2**attempt) if exponential_backoff else base_delay,
                        max_delay,
                    )
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_attempts} for {func.__name__} failed: {e}. "
                        f"Retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)

        return wrapper

    return decorator


def sync_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_backoff: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator for synchronous functions with retry logic and exponential backoff.

    Args:
        max_attempts: Total number of attempts before raising the last exception.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound on the computed delay between retries.
        exponential_backoff: If True, doubles the delay on each attempt.
        exceptions: Tuple of exception types that trigger a retry.

    Returns:
        A decorator that wraps the target function with retry behaviour.
    """

    def decorator(func: Callable) -> Callable:
        """Wrap a synchronous function with the configured retry behaviour."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}: {e}")
                        raise
                    delay = min(
                        base_delay * (2**attempt) if exponential_backoff else base_delay,
                        max_delay,
                    )
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_attempts} for {func.__name__} failed: {e}. "
                        f"Retrying in {delay}s"
                    )
                    time.sleep(delay)

        return wrapper

    return decorator
