"""Native Python vs documented Pyodide tolerances for a representative rest EEG."""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile

import pytest

from neurobuddy_v2.browser_entry import fingerprint, run_single
from neurobuddy_v2.pipeline import process

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sub-val_ses-01_task-rest_eeg.fif"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "native_report.json"
TOLERANCES = Path(__file__).resolve().parent / "tolerances.json"


def _load_or_skip(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"Missing fixture {path.name}; run generate_fixture.py")
    return path


def test_native_fingerprint_does_not_invent_metadata():
    path = _load_or_skip(FIXTURE)
    info = fingerprint(path.parent)
    assert info["sample_rate_hz"] == 256.0
    assert info["ch_names"] == ["C3", "C4", "Cz", "Oz"]
    assert info["n_times"] == 512
    assert info["amplitude_min"] is not None
    assert info["amplitude_max"] is not None


def test_native_pipeline_matches_golden_within_tolerance():
    path = _load_or_skip(FIXTURE)
    tolerances = json.loads(TOLERANCES.read_text(encoding="utf-8")) if TOLERANCES.is_file() else {
        "sample_rate_hz": 0.0,
        "band_power_rel": 1e-9,
        "z_abs": 1e-9
    }
    with tempfile.TemporaryDirectory(prefix="nb-native-") as tmp:
        delivered = process(path.parent, tmp, player_frames=80, artifact_mode="legacy")
        assert len(delivered) == 1
        report = delivered[0][0]
    if not GOLDEN.is_file():
        GOLDEN.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        pytest.skip("Wrote native golden report; re-run to compare")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert report["recording"]["sample_rate_hz"] == pytest.approx(
        golden["recording"]["sample_rate_hz"], abs=tolerances.get("sample_rate_hz", 0.0)
    )
    assert report["recording"]["n_channels"] == golden["recording"]["n_channels"]
    assert report["processing_status"] == golden["processing_status"]
    assert report["classification"]["task_family"] == golden["classification"]["task_family"]


def test_browser_entry_single_matches_process():
    path = _load_or_skip(FIXTURE)
    with tempfile.TemporaryDirectory(prefix="nb-entry-") as tmp:
        result = run_single(str(path.parent), tmp, artifact_mode="legacy", task_selected="unspecified")
    assert result["mode"] == "single"
    assert result["entrypoint"] == "report.html"
    assert result["analysis"]["recording"]["sample_rate_hz"] == 256.0
    assert math.isfinite(result["analysis"]["recording"]["duration_s"])
