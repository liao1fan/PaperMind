"""Exponential backoff retry decorator using backoff library."""

import functools
from typing import Any, Callable, Type, TypeVar

import backoff
from backoff import on_exception

from .logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def exponential_backoff(
    max_tries: int = 5,
    max_time: int = 300,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    base: float = 2.0,
    factor: float = 1.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for exponential backoff retry logic.

    Args:
        max_tries: Maximum number of retry attempts
        max_time: Maximum total time in seconds for retries
        exceptions: Tuple of exception types to retry on
        base: Base for exponential backoff (default: 2)
        factor: Multiplier for backoff delay (default: 1)

    Returns:
        Decorated function with retry logic

    Example:
        @exponential_backoff(max_tries=3, exceptions=(httpx.HTTPError,))
        async def fetch_data():
            return await client.get("/data")
    """

    def on_backoff_handler(details: dict[str, Any]) -> None:
        """Log backoff events."""
        logger.warning(
            "Retrying after exception",
            exception=str(details.get("exception")),
            tries=details.get("tries"),
            wait=details.get("wait"),
            target=details.get("target"),
        )

    def on_giveup_handler(details: dict[str, Any]) -> None:
        """Log when giving up."""
        logger.error(
            "Giving up after exhausting retries",
            exception=str(details.get("exception")),
            tries=details.get("tries"),
            elapsed=details.get("elapsed"),
            target=details.get("target"),
        )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @on_exception(
            backoff.expo,
            exceptions,
            max_tries=max_tries,
            max_time=max_time,
            base=base,
            factor=factor,
            on_backoff=on_backoff_handler,
            on_giveup=on_giveup_handler,
        )
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await func(*args, **kwargs)

        return wrapper

    return decorator
