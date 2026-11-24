"""Browser/Pyodide analysis entry. No HTTP, temp-server roots, or Flask/FastAPI.

The Coach web worker copies EEG bytes into a virtual filesystem, then calls
these functions. Scientific work stays in pipeline.process and
comparative.run_athlete_workflow.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MNE_DATA", "/tmp/mne-data")
os.environ.setdefault("HOME", "/home/pyodide")


def json_safe(value):
    """Store pipeline JSON without changing calculations. Non-finite floats cannot be strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def list_outputs(output: Path) -> list[str]:
    if not output.exists():
        return []
    files = []
    for path in output.rglob("*"):
        if path.is_file():
            files.append(str(path.relative_to(output)).replace("\\", "/"))
    return sorted(files)


def run_single(source_dir: str, output_dir: str, *, artifact_mode: str = "legacy",
               mains_frequency_hz: float = 60.0, player_frames: int = 1500,
               large_threshold_mb: int = 256, chunk_seconds: int = 60,
               sleep_staging: str = "if_missing", task_selected: str = "unspecified") -> dict:
    from neurobuddy_v2.pipeline import process

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    delivered = process(
        Path(source_dir), dest,
        player_frames=player_frames,
        large_threshold_mb=large_threshold_mb,
        chunk_seconds=chunk_seconds,
        sleep_staging=sleep_staging,
        artifact_mode=artifact_mode,
        mains_frequency_hz=mains_frequency_hz,
    )
    if len(delivered) != 1:
        raise ValueError("Expected exactly one EEG recording.")
    report = delivered[0][0]
    actual = report.get("classification", {}).get("task_family", "UNKNOWN").lower()
    selected = (task_selected or "unspecified").lower()
    mismatch = selected != "unspecified" and actual != "unknown" and actual != selected
    warning = None
    if mismatch:
        warning = (
            f"Selected {selected}, but EEG events/metadata indicate {actual}. "
            "Review the task object/annotations."
        )
    return json_safe({
        "mode": "single",
        "analysis": report,
        "task_selected": selected,
        "task_detected": actual,
        "task_warning": warning,
        "entrypoint": "report.html",
        "package": "report.zip",
        "outputs": list_outputs(dest),
    })


def run_athlete(baseline_dirs: list[str], test_dir: str, output_dir: str, *,
                team_id: str, athlete_id: str, artifact_mode: str = "legacy",
                mains_frequency_hz: float = 60.0, min_baselines: int | None = None,
                player_frames: int = 1500, large_threshold_mb: int = 256,
                chunk_seconds: int = 60, sleep_staging: str = "if_missing") -> dict:
    from neurobuddy_v2.comparative import baseline_minimum, run_athlete_workflow

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    needed = min_baselines if min_baselines is not None else 3
    struct = run_athlete_workflow(
        baseline_dirs, test_dir, dest,
        team_id=team_id, athlete_id=athlete_id,
        min_baselines=needed,
        player_frames=player_frames,
        large_threshold_mb=large_threshold_mb,
        chunk_seconds=chunk_seconds,
        sleep_staging=sleep_staging,
        artifact_mode=artifact_mode,
        mains_frequency_hz=mains_frequency_hz,
    )
    comparison = json.loads((dest / "comparative_analysis.json").read_text(encoding="utf-8"))
    baseline = json.loads((dest / "baseline" / "longitudinal.json").read_text(encoding="utf-8"))
    individual = []
    for item in struct["baseline_reports"]:
        individual.append({
            "classification": "baseline",
            "result": json.loads((dest / item["report_json"]).read_text(encoding="utf-8")),
            "entrypoint": item["report_html"],
        })
    individual.append({
        "classification": "testing",
        "result": json.loads((dest / "test" / "report.json").read_text(encoding="utf-8")),
        "entrypoint": "test/report.html",
    })
    return json_safe({
        "mode": "athlete",
        "athlete_id": athlete_id,
        "team_id": team_id,
        "comparison": comparison,
        "baseline": baseline,
        "individual": individual,
        "summary": struct["comparison_summary"],
        "entrypoint": "athlete_report.html",
        "package": "athlete_report.zip",
        "outputs": list_outputs(dest),
    })


def fingerprint(source_dir: str) -> dict:
    """Read-only metadata used by the validation suite. Does not invent labels or Hz."""
    import mne
    from neurobuddy_v2.intake import discover, load_eeg

    bundles = discover(source_dir)
    if not bundles:
        raise ValueError("No supported EEG recording found.")
    bundle = bundles[0]
    raw = load_eeg(bundle)
    try:
        info = {
            "file": bundle.signal.name,
            "sample_rate_hz": float(raw.info["sfreq"]),
            "n_channels": int(len(raw.ch_names)),
            "ch_names": list(raw.ch_names),
            "n_times": int(raw.n_times),
            "duration_s": float(raw.n_times / raw.info["sfreq"]) if raw.info["sfreq"] else None,
            "channel_types": list(raw.get_channel_types()),
            "mne_version": mne.__version__,
        }
        data = raw.get_data()
        info["amplitude_min"] = float(data.min()) if data.size else None
        info["amplitude_max"] = float(data.max()) if data.size else None
        info["amplitude_mean"] = float(data.mean()) if data.size else None
        return json_safe(info)
    finally:
        raw.close()
