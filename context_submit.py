"""Thread-pool submission that preserves the caller's ContextVar state."""
from __future__ import annotations

from concurrent.futures import Executor, Future
from contextvars import copy_context
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def submit_with_context(
    executor: Executor,
    func: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> Future[T]:
    """Submit one task with an independent copy of the current context."""
    context = copy_context()
    return executor.submit(context.run, func, *args, **kwargs)
