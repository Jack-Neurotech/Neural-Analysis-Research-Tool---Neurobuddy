"""Guard the three v0.3.1 frontend fixes against accidental regression."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_single_native_download_picker_and_retry():
    script = source("v2/shelf-ui.js")
    assert "showOpenFilePicker" not in script
    assert "input.click();" in script
    assert "$('choose-downloads').addEventListener" in script
    assert "$('retry-upload').addEventListener" in script
    assert "state.selectedFiles" in script


def test_redundant_select_shelf_button_removed():
    script = source("v2/shelf-ui.js")
    assert "Select Shelf</button>" not in script
    assert 'title="Open shelf file slots"' in script
    assert 'data-select-type="single"' in script


def test_analysis_uses_original_generated_html():
    script = source("v2/app.js")
    assert "reportForJob(id,job.result)" in script
    assert "Open full EEG HTML report" in script
    assert "Open full longitudinal HTML report" in script
    assert "Open athlete HTML report" in script
    assert "renderSingle(" not in script
    assert "rowsTable(" not in script
    assert "comparative_analysis.csv" in script


def test_unchanged_navigation_and_in_modal_status():
    page = source("Index.html")
    for tab in ('library', 'analysis', 'advanced'):
        assert f'data-tab="{tab}"' in page
    assert 'id="import-status"' in page
    assert 'id="retry-upload"' in page
    assert 'id="native-file-picker"' in page


def test_shareable_link_can_be_copied_without_live_server():
    page = source("Index.html")
    script = source("v2/app.js")
    adapter = source("v2/browser-api.js")
    assert 'src="v2/browser-api.js"' in page
    assert 'src="v2/browser-store.js"' in page
    assert 'id="copy-share-link"' in page
    assert 'id="copy-share-link-header"' in page
    assert 'id="share-url"' in page
    assert "copyShareLink" in script
    assert "navigator.clipboard.writeText" in adapter
    assert "browser-native" in adapter
    assert "pyodide-worker.js" in adapter
