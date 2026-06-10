from __future__ import annotations

import json

import pytest


class FakeClock:
    """Monotonic-ish clock: returns the current value, then advances by `step`.
    Lets the not-found / max-duration timeouts fire deterministically without
    real time passing."""

    def __init__(self, step: float = 1.0):
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.t
        self.t += self.step
        return value


async def _noop_sleep(_seconds: float) -> None:
    return None


def _make_fetch(items):
    iterator = iter(items)
    last = {"value": None}

    async def fetch():
        try:
            last["value"] = next(iterator)
        except StopIteration:
            pass
        return last["value"]

    return fetch


async def _collect(generator):
    frames = []
    async for frame in generator:
        frames.append(frame)
    return frames


def _data_payloads(frames):
    payloads = []
    for frame in frames:
        if frame.startswith("data: "):
            payloads.append(json.loads(frame[len("data: "):].strip()))
    return payloads


def _status(progress, status="processing", message="working"):
    return {
        "task_id": "t-1",
        "status": status,
        "progress": progress,
        "message": message,
        "result": None,
        "error": None,
        "metadata": None,
    }


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_streams_each_changed_status_until_completed():
    import main

    fetch = _make_fetch([
        _status(10),
        _status(50),
        _status(100, status="completed", message="ready"),
    ])
    frames = await _collect(
        main.sse_task_status_frames(fetch, "t-1", interval=0, now=FakeClock(), sleep=_noop_sleep)
    )

    # Stream opens with a comment frame so the client connects promptly.
    assert frames[0] == ": connected\n\n"
    payloads = _data_payloads(frames)
    assert [p["progress"] for p in payloads] == [10, 50, 100]
    assert payloads[-1]["status"] == "completed"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_unchanged_status_is_not_re_emitted():
    import main

    fetch = _make_fetch([
        _status(50),
        _status(50),  # identical → must be skipped
        _status(100, status="completed", message="ready"),
    ])
    frames = await _collect(
        main.sse_task_status_frames(fetch, "t-1", interval=0, now=FakeClock(), sleep=_noop_sleep)
    )

    payloads = _data_payloads(frames)
    assert [p["progress"] for p in payloads] == [50, 100]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_missing_task_emits_terminal_error_frame():
    import main

    async def fetch_none():
        return None

    frames = await _collect(
        main.sse_task_status_frames(
            fetch_none,
            "t-missing",
            interval=0,
            not_found_timeout=10,
            now=FakeClock(step=5),
            sleep=_noop_sleep,
        )
    )

    payloads = _data_payloads(frames)
    assert len(payloads) == 1
    assert payloads[0]["status"] == "error"
    assert payloads[0]["task_id"] == "t-missing"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_stops_when_client_disconnects():
    import main

    async def disconnected():
        return True

    fetch = _make_fetch([_status(10)])
    frames = await _collect(
        main.sse_task_status_frames(
            fetch,
            "t-1",
            is_disconnected=disconnected,
            interval=0,
            now=FakeClock(),
            sleep=_noop_sleep,
        )
    )

    # Only the initial comment frame; the loop exits before fetching any status.
    assert frames == [": connected\n\n"]
