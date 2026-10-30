import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
from types import SimpleNamespace

from api.ai.pipeline import _generation_slot
from api.ai.cloud_provider import FallbackProvider
from api.ai.providers import AIProviderError, LOCAL_GENERATION_LOCK


def test_cloud_requests_overlap_but_have_bounded_fanout():
    local, cloud = object(), object()
    active = maximum = 0
    async def one():
        nonlocal active, maximum
        async with _generation_slot(cloud, local):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.005)
            active -= 1
    async def run():
        await asyncio.gather(*(one() for _ in range(9)))
    asyncio.run(run())
    assert maximum == 4


def test_cancelled_cloud_waiter_does_not_leak_a_slot():
    async def run():
        local, cloud = object(), object()
        slot = _generation_slot(cloud, local)
        for _ in range(4):
            await slot.acquire()
        waiter = asyncio.create_task(slot.acquire())
        await asyncio.sleep(0)
        waiter.cancel()
        try:
            await waiter
        except asyncio.CancelledError:
            pass
        for _ in range(4):
            slot.release()
        for _ in range(4):
            await asyncio.wait_for(slot.acquire(), timeout=0.1)
        for _ in range(4):
            slot.release()
    asyncio.run(run())


def test_cloud_fallback_and_direct_local_generation_share_the_same_thread_lock():
    active = maximum = 0
    def local_generate(**kwargs):
        nonlocal active, maximum
        with LOCAL_GENERATION_LOCK:
            active += 1
            maximum = max(maximum, active)
            time.sleep(0.005)
            active -= 1
        return "local"
    def unavailable(**kwargs):
        raise AIProviderError("test unavailable")
    local = SimpleNamespace(name="ollama", model="fixture", generate=local_generate)
    primary = SimpleNamespace(name="openrouter", model="fixture", generate=unavailable)
    fallback = FallbackProvider(primary=primary, fallback=local)
    with ThreadPoolExecutor(max_workers=3) as pool:
        a = pool.submit(local_generate)
        b = pool.submit(fallback.generate, system_instruction="test", prompt="test")
        assert a.result() == b.result() == "local"
    assert maximum == 1 and fallback.fell_back
