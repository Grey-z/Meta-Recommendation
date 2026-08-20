"""Drift guard: scripts/probe_solver.py must match the generated transform.

The probe is a mechanical fork of itinerary_solver.py produced by
scripts/sync_probe_solver.py. It once shipped stale — missing the post-loop
finals harvest, so every multi-day calibration sweep ranked a biased sample of
plans. This test fails the moment the solver changes without the probe being
regenerated; the fix is one command: python scripts/sync_probe_solver.py.
"""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.backend_unit

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_probe_solver", BACKEND_ROOT / "scripts" / "sync_probe_solver.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_solver_matches_generated_transform():
    sync = _load_sync_module()
    expected = sync.generate(sync.SOLVER_PATH.read_text(encoding="utf-8"))
    actual = sync.PROBE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, (
        "scripts/probe_solver.py lags langgraph_metarec/itinerary_solver.py; "
        "run: python scripts/sync_probe_solver.py"
    )


def test_generated_probe_is_valid_python_with_instrumentation():
    sync = _load_sync_module()
    generated = sync.generate(sync.SOLVER_PATH.read_text(encoding="utf-8"))
    compile(generated, "probe_solver.py", "exec")
    # Both beam trims and both final rankings must be instrumented.
    assert generated.count('PROBE["trim"].append') == 2
    assert generated.count("_record_final(") >= 3  # def + two call sites
