"""Process ownership for native handles, with a separate short-request lane."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import asyncio
import atexit

from .service import SearchStore

_store = None


def _initialize(collections, options):
    global _store
    _store = SearchStore(collections, **options)
    atexit.register(_store.close)


def _dispatch(operation, args, kwargs):
    if operation not in {"search", "page", "fetch", "fields", "scan", "info"}:
        raise ValueError("Unknown service operation")
    return getattr(_store, operation)(*args, **kwargs)


class SearchWorkers:
    def __init__(self, collections, **options):
        context = get_context("spawn")
        self.pools = [ProcessPoolExecutor(max_workers=1, mp_context=context,
                         initializer=_initialize, initargs=(collections, options))
                      for _ in range(2)]

    async def call(self, operation, *args, **kwargs):
        pool = self.pools[1 if operation in {"fields", "scan"} else 0]
        return await asyncio.wrap_future(pool.submit(_dispatch, operation, args, kwargs))

    def close(self):
        for pool in self.pools:
            pool.shutdown(wait=True, cancel_futures=True)
