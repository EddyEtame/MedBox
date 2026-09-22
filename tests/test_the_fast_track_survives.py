"""The fast track outlives anything that goes wrong inside one tick.

`MedBox.loop()` IS the fast track: sample, score, quarantine, broadcast, ten
times a second. It is one asyncio task, and an exception that escapes a task
ends it without a word. The WebSocket stays open and /api/status keeps
answering, so from outside the station looks healthy while the board shows the
last numbers it will ever show.

Measured before the guard: a scenario step with `temperature: 39,5` (a French
decimal comma, which YAML reads as a string) took the board from ten frames a
second to zero, three seconds after Run, with nothing in the log.

The other direction matters too: stopping the station must not wait forever on
a task that will not stop. A cancel that lands inside an httpx request can be
swallowed there, and the AI watcher then polled on while shutdown waited for
it. That hung the station every time its port was already taken.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402
from server.scenarios import Scenario, Step  # noqa: E402


def test_a_scenario_step_that_cannot_run_is_skipped_out_loud(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(station.BUS, "publish", sent.append)
    box = station.STATION
    box.scenario = Scenario(
        "decimal comma", "", 40,
        [Step(0.0, "afflict", {"patients": 1, "temperature": "39,5"})],
    )
    box.scenario_t0 = time.monotonic()
    box._fired.clear()
    try:
        box._frame()
        box._frame()
    finally:
        box.stop_scenario()

    assert [m.get("type") for m in sent].count("board") == 2, (
        "the board stopped being published after a scenario step failed"
    )
    notes = [m.get("text", "") for m in sent if m.get("kind") == "warning"]
    assert any("skipped" in n and "39,5" in n for n in notes), (
        f"the operator was not told a step was skipped: {notes}"
    )


def test_one_failing_tick_does_not_end_the_loop(monkeypatch):
    calls: list[int] = []

    def frame() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("one bad tick")

    monkeypatch.setattr(station.STATION, "_frame", frame)

    async def run() -> None:
        task = asyncio.create_task(station.STATION.loop())
        await asyncio.sleep(0.35)
        task.cancel()
        await asyncio.wait({task}, timeout=1.0)

    asyncio.run(run())
    assert len(calls) >= 3, (
        f"the loop ran {len(calls)} tick(s) in 0.35 s: the first failure ended "
        "the fast track"
    )


def test_asking_after_the_assistant_does_not_stall_the_loop(monkeypatch):
    """probe() runs every five seconds on the same event loop as the board.

    Each httpx.AsyncClient() used to build an SSL context from certifi's
    bundle, synchronously: on the demo laptop the loop froze for up to 1.1 s
    per probe, so the board lost about ten frames every five seconds. Mostly a
    Windows problem; on a fast Linux box this passes either way.
    """
    monkeypatch.setattr(station.CLIENT, "host", "http://127.0.0.1:9")  # nothing listens

    async def run() -> float:
        gaps: list[float] = []
        done = asyncio.Event()

        async def ticker() -> None:
            last = time.perf_counter()
            while not done.is_set():
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        tick = asyncio.create_task(ticker())
        await asyncio.sleep(0.05)
        await station.CLIENT.probe()
        done.set()
        await tick
        return max(gaps)

    worst = asyncio.run(run())
    assert worst < 0.25, (
        f"the event loop stood still for {worst * 1000:.0f} ms during a probe; "
        "the board ticks every 100 ms"
    )


def test_the_ai_watcher_stops_even_when_its_cancel_is_swallowed(monkeypatch):
    async def swallowing_probe() -> bool:
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass  # what httpx was measured doing to a cancel mid-request
        return True

    monkeypatch.setattr(station.CLIENT, "probe", swallowing_probe)

    async def run() -> bool:
        task = asyncio.create_task(station.STATION.watch_ai())
        await asyncio.sleep(0.05)  # inside the probe
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2.0)
        return bool(done)

    assert asyncio.run(run()), (
        "watch_ai went on polling after it was cancelled, so shutdown would "
        "wait on it forever"
    )
