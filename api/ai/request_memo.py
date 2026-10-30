"""Single-flight memoization owned by one answer request, never a global cache."""
from concurrent.futures import Future
from functools import wraps
from threading import Lock


def memoize_request(function):
    """Share identical in-flight work and successful results within this closure.

    Exact keys only: no question rewriting or cross-user reuse. Failures are
    evicted so an optional branch's transient error does not poison retries.
    """
    lock = Lock()
    entries = {}

    @wraps(function)
    def wrapped(value):
        with lock:
            future = entries.get(value)
            owner = future is None
            if owner:
                future = entries[value] = Future()
        if not owner:
            return future.result()
        try:
            result = function(value)
        except BaseException as error:
            future.set_exception(error)
            with lock:
                if entries.get(value) is future:
                    del entries[value]
            raise
        future.set_result(result)
        return result

    return wrapped
