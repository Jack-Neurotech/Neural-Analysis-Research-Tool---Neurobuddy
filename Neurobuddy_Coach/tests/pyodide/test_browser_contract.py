"""Guard the browser-native Pyodide adapter against accidental sample-data fallbacks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_index_loads_pyodide_stack_not_sample_adapter():
    page = source("Index.html")
    assert 'src="v2/browser-store.js"' in page
    assert 'src="v2/browser-api.js"' in page
    assert 'src="v2/hosted-api.js"' not in page
    assert 'rel="manifest"' in page
    assert 'id="backup-workspace"' in page
    assert 'id="restore-workspace"' in page
    for tab in ("library", "analysis", "advanced"):
        assert f'data-tab="{tab}"' in page


def test_browser_api_runs_worker_not_simulated_metrics():
    script = source("v2/browser-api.js")
    assert "pyodide-worker.js" in script
    assert "mode: 'browser-native'" in script or "mode: 'browser-native'" in script.replace('"', "'")
    assert "sample_data: false" in script
    assert "12.4" not in script
    assert "Demo Track Club" not in script
    assert "flask" not in script.lower()
    assert "uvicorn" not in script.lower()


def test_worker_reuses_pipeline_entry():
    worker = source("v2/pyodide-worker.js")
    assert "neurobuddy_v2.browser_entry" in worker
    assert "run_single" in worker
    assert "run_athlete" in worker
    assert "mne==1.8.0" in worker
    entry = source("neurobuddy_v2/browser_entry.py")
    assert "from neurobuddy_v2.pipeline import process" in entry
    assert "from neurobuddy_v2.comparative import baseline_minimum, run_athlete_workflow" in entry
