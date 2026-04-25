import functools
import inspect
import time
from typing import Any

from friday.logger import logger


def _validate_string_inputs(
    func_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    max_str_len: int,
) -> str | None:
    """Return a user-facing validation error when any string input is too large."""
    for i, arg in enumerate(args):
        if isinstance(arg, str) and len(arg) > max_str_len:
            logger.warning(
                "Validation failed: argument %s exceeded max length %s in %s",
                i,
                max_str_len,
                func_name,
            )
            return (
                "[Security Block] "
                f"Argument {i} exceeded maximum allowed length of {max_str_len} characters."
            )

    for key, val in kwargs.items():
        if isinstance(val, str) and len(val) > max_str_len:
            logger.warning(
                "Validation failed: kwarg '%s' exceeded max length %s in %s",
                key,
                max_str_len,
                func_name,
            )
            return (
                "[Security Block] "
                f"Input '{key}' exceeded maximum allowed length of {max_str_len} characters."
            )

    return None


def safe_tool(func):
    """
    Decorator to standardize error handling and add performance monitoring across F.R.I.D.A.Y. tools.
    Catches any unhandled exceptions, returns a consistently formatted error string,
    and logs the execution time. Supports both sync and async functions.
    """
    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            tool_name = func.__name__
            try:
                logger.debug(f"Executing tool: {tool_name}")
                result = await func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.info(f"Tool '{tool_name}' completed in {elapsed:.3f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"Tool '{tool_name}' failed after {elapsed:.3f}s: {str(e)}",
                    exc_info=True,
                )
                return f"[Tool Error] - {tool_name}: {str(e)}"

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        tool_name = func.__name__
        try:
            logger.debug(f"Executing tool: {tool_name}")
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"Tool '{tool_name}' completed in {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"Tool '{tool_name}' failed after {elapsed:.3f}s: {str(e)}",
                exc_info=True,
            )
            return f"[Tool Error] - {tool_name}: {str(e)}"

    return sync_wrapper


def validate_inputs(max_str_len: int = 10000):
    """
    Decorator to prevent memory exhaustion from oversized string inputs.
    Validates all string arguments and kwargs before execution.
    Supports both sync and async functions.
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                validation_error = _validate_string_inputs(
                    func.__name__, args, kwargs, max_str_len
                )
                if validation_error:
                    return validation_error
                return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            validation_error = _validate_string_inputs(
                func.__name__, args, kwargs, max_str_len
            )
            if validation_error:
                return validation_error
            return func(*args, **kwargs)

        return wrapper

    return decorator
