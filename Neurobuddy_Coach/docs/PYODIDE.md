# NeuroBuddy Pyodide migration

This document is the Phase 1 dependency audit and the record of what the
browser-native runtime can and cannot execute. Scientific algorithms live in
`neurobuddy_v2/` and are reused unchanged. The FastAPI server in `backend/`
is retained for local development; the production Pages app does not call it.

Pinned runtime: **Pyodide 0.28.3** (CPython 3.13). See
`pyodide/pinned-packages.json`.

## Dependency categories

| Package | Role | Category | Browser status |
|---|---|---|---|
| numpy 2.2.5 | Arrays, FFT inputs | Native Pyodide | `loadPackage` |
| scipy 1.14.1 | Filters, PSD, stats, `loadmat` (MATLAB Level 5) | Native Pyodide | `loadPackage` |
| pandas 2.3.1 | Event / annotation tables | Native Pyodide | `loadPackage` |
| matplotlib 3.8.4 | Report figures (Agg) | Native Pyodide | `loadPackage`; `MPLBACKEND=Agg` |
| h5py 3.13.0 | MATLAB v7.3 / HDF5 `.set` | Native Pyodide | `loadPackage` |
| scikit-learn 1.7.0 | Unused by the v0.7.1 pipeline today | Native Pyodide | Available; not loaded at startup |
| mne 1.8.0 | EEG I/O and analysis | micropip (`py3-none-any`) | Installed at worker init |
| pymatreader | EEGLAB MATLAB v7.3 via h5py | micropip | Installed at worker init |
| jsonschema / fastjsonschema | Report schema check | micropip | Installed at worker init |
| lazy-loader, pooch, tqdm, platformdirs, decorator | MNE dependencies | micropip | Installed at worker init |
| yasa, lightgbm, antropy, numba | Optional automatic sleep staging | Currently incompatible | Import is already optional; annotated sleep still runs |
| fastapi, uvicorn, python-multipart, httpx | HTTP server | Architectural adaptation | Not imported in the worker |
| sqlite3 | Local Coach DB | Architectural adaptation | Replaced by IndexedDB + OPFS |
| subprocess / osascript | macOS file picker in `legacy_combined` | Architectural adaptation | Never called from the browser entry |

CSV, TSV, and TXT remain **annotation / sidecar** formats. They are not treated
as raw EEG signals and sampling frequency is never guessed.

## EEG formats

| Format | Reader | Notes |
|---|---|---|
| EDF / BDF | `mne.io.read_raw_edf` / `read_raw_bdf` | Unchanged |
| EEGLAB `.set` + `.fdt` | `mne.io.read_raw_eeglab` | Companion must be stored next to the `.set` in the worker FS |
| MATLAB Level 5 `.set` | scipy `loadmat` inside MNE | |
| MATLAB v7.3 / HDF5 `.set` | h5py + pymatreader inside MNE | |
| BrainVision `.vhdr` + `.eeg` + `.vmrk` | `read_raw_brainvision` | Companions kept together |
| FIF / FIF.GZ | `read_raw_fif` | |
| Events / sleep stages | pandas via `events.py` | `.tsv` `.csv` `.json` `.txt` |

## Frontend API replacement

Every `fetch('/api/...')` from `v2/app.js` and `v2/shelf-ui.js` is intercepted
by `v2/browser-api.js` when no live uvicorn server answers
`GET /api/v2/health` with `mode: local-only`. Messages go to the Pyodide worker.
Request and response shapes match the FastAPI routes.

User EEG and athlete records stay in IndexedDB / OPFS on the originating
origin. OpenNeuro GraphQL and file URLs are the only optional outbound calls,
and only when the user opens the Connector.

## Known blockers

1. **YASA automatic staging** needs numba and lightgbm WASM builds. The pipeline
   already degrades to annotation-driven sleep metrics when YASA is absent.
2. **SharedArrayBuffer interrupt** needs Cross-Origin Isolation headers that
   GitHub Pages does not set. Cancel terminates the worker and starts a new one.
3. **OpenNeuro S3 downloads** may be blocked by CORS for `github.io`. Metadata
   browse still works when GraphQL CORS allows it; otherwise the user imports
   from Downloads.
4. **Dataset size**. Chromium tab memory, not the algorithm, is the limit.
   Recordings under ~50 MB of samples are the supported interactive size.
   The existing streaming path (`large_recordings`) still runs above 256 MiB
   but the browser may OOM before Python does.
5. **Pyodide numpy 2.2 vs pipeline `numpy>=1.26`**. Numeric results are compared
   in `tests/pyodide/` with documented tolerances. Algorithms are not changed
   to paper over differences.

## Validation (executed)

Representative rest FIF (`tests/pyodide/fixtures/sub-val_ses-01_task-rest_eeg.fif`,
4 channels, 256 Hz, 2 s) was processed with:

1. Native CPython 3.12 + MNE 1.8.0 + SciPy 1.14.1
2. Pyodide 0.28.3 + the same MNE 1.8.0 wheel inside Node

Results: `processing_status=COMPLETE`, `task_family=GENERAL`, sampling
frequency 256 Hz, 4 channels. A recursive JSON walk of the full native vs
Pyodide `report.json` found **0 numeric or structural differences** outside
ignored provenance timestamps. Elapsed analysis time in this environment was
about 4.1 s after the runtime was loaded.

Init in a cold Node process downloaded the scientific wheels from the pinned
jsDelivr Pyodide 0.28.3 index (numpy/scipy/matplotlib/pandas/h5py/MNE). Browser
tabs will see a longer first-visit init while those assets cache.

## Network audit

| Request | When | User data? |
|---|---|---|
| `cdn.jsdelivr.net/pyodide/v0.28.3/full/*` | Runtime init | No (application assets) |
| PyPI wheels via micropip (MNE and pure-Python deps) | Runtime init | No |
| `openneuro.org/crn/graphql` and OpenNeuro/S3 file URLs | Only after Connector use | Dataset ids the user typed; no athlete records uploaded |
| GitHub Pages static files | Page load | No |

No EEG recordings, athlete names, or analysis results are posted to a
computational API.

## Privacy

- No EEG bytes, athlete names, or reports are posted to a computational API.
- Pyodide, micropip, and MNE wheels are application assets (CDN or `vendor/`).
- OpenNeuro traffic happens only after the Connector is used.
