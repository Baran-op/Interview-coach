"""One worker thread for all MLX work (Whisper and Kokoro).

MLX models are loaded and run on the same thread, one job at a time, so the two
models never compete for the M1 GPU or its 8 GB of shared memory, and the
asyncio event loop stays free while they run.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")


def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    return _executor.submit(fn, *args, **kwargs)


async def run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.wrap_future(submit(fn, *args, **kwargs))
