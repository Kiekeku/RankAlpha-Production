"""Shared helpers for working with API settings.

This module centralizes the common "cached Settings with test-safe behavior" pattern
used across routers and dependencies.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Callable, TypeVar, cast

T = TypeVar("T")


def _is_test_environment() -> bool:
    return "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))


def make_cached_getter(
    factory: Callable[[], T],
    *,
    cache_in_tests: bool = False,
) -> Callable[[], T]:
    """Return a test-aware cached getter around *factory*.

    - In production: returns a single cached instance.
    - In tests: returns a fresh instance each call unless `cache_in_tests=True`.

    The returned function exposes `.cache_clear()` and `.cache_info()` like an
    `@lru_cache` function, so existing tests can clear caches after env changes.
    """

    @lru_cache
    def _cached() -> T:
        return factory()

    def _get() -> T:
        if _is_test_environment() and not cache_in_tests:
            return factory()
        return _cached()

    # Expose lru_cache controls on the wrapper for compatibility with call sites/tests.
    _get.cache_clear = cast(object, _cached).cache_clear  # type: ignore[attr-defined]
    _get.cache_info = cast(object, _cached).cache_info  # type: ignore[attr-defined]
    return _get
