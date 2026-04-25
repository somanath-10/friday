import functools
import json
import hashlib
import inspect
import time
from typing import Callable

from friday.logger import logger

_MEMORY_CACHE = {}

def _generate_cache_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """Generate a unique cache key for a function call."""
    key_dict = {
        "func": func.__name__,
        "args": args,
        "kwargs": kwargs
    }
    # Handle non-serializable objects by converting to string
    try:
        key_str = json.dumps(key_dict, sort_keys=True, default=str)
    except Exception:
        key_str = str(key_dict)

    return hashlib.md5(key_str.encode('utf-8')).hexdigest()

def cached_tool(ttl_seconds: int = 3600):
    """
    Decorator to cache the results of expensive tool calls in memory.
    Supports both sync and async functions.
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                cache_key = _generate_cache_key(func, args, kwargs)
                if cache_key in _MEMORY_CACHE:
                    entry = _MEMORY_CACHE[cache_key]
                    if time.time() - entry["timestamp"] < ttl_seconds:
                        logger.debug(f"Cache HIT for {func.__name__} (TTL: {ttl_seconds}s)")
                        return entry["result"]
                    del _MEMORY_CACHE[cache_key]

                logger.debug(f"Cache MISS for {func.__name__}. Executing...")
                result = await func(*args, **kwargs)
                _MEMORY_CACHE[cache_key] = {"timestamp": time.time(), "result": result}
                return result
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                cache_key = _generate_cache_key(func, args, kwargs)
                if cache_key in _MEMORY_CACHE:
                    entry = _MEMORY_CACHE[cache_key]
                    if time.time() - entry["timestamp"] < ttl_seconds:
                        logger.debug(f"Cache HIT for {func.__name__} (TTL: {ttl_seconds}s)")
                        return entry["result"]
                    del _MEMORY_CACHE[cache_key]

                logger.debug(f"Cache MISS for {func.__name__}. Executing...")
                result = func(*args, **kwargs)
                _MEMORY_CACHE[cache_key] = {"timestamp": time.time(), "result": result}
                return result
            return sync_wrapper
    return decorator

def clear_cache():
    """Clear the in-memory tool cache."""
    _MEMORY_CACHE.clear()
    logger.info("Tool cache cleared.")
