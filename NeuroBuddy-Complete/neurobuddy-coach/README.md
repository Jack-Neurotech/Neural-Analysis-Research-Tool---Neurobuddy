# Neurobuddy Coach Atlas v0.3.1 · EEG Shelf Workspace (Upload and HTML Report Fixes)

**Frontend:** The original pre-Repository three-tab Neurobuddy dark-theme website.
**Scientific backend:** The latest delivered standalone **Neurobuddy v0.7.1 Optimized** pipeline, with localized experimental artifact screening, optimized spectral analysis, bounded-memory streaming, longitudinal athlete analysis, interactive report output and 0.7.1 provenance.

This project is the **central Dataset Library as Repository** concept. It is not the earlier separate Repository/EEG Collection interface. All data shown in the actual Library is backed by local SQLite and files, not fake browser-only cards.

## Run locally on Mac / Linux

From the folder containing `Neurobuddy_Coach_v0.3.1_Import_Report_Fixes.zip`:

```bash
unzip Neurobuddy_Coach_v0.3.1_Import_Report_Fixes.zip
cd Neurobuddy_Coach_v0.3.1_Import_Report_Fixes
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765 --reload
```

Open **http://127.0.0.1:8765/**. Do **not** launch `Index.html` through VS Code Live Server, as scientific data and persistent state require FastAPI. Windows: create a venv with `py -m venv .venv`, activate with `.venv\Scripts\activate`, and use `python -m ...` for the rest.

The app creates `data/coach.sqlite3`, `data/recordings/<uuid>/` and `data/reports/<job-uuid>/` at first run. Set `NEUROBUDDY_DATA_DIR` before starting to redirect persistence.

## Three-tab website

1. **Dataset Library (central Repository)**: team and athlete folders, per-athlete EEG shelves, global `TEST TYPE` and `FILE TYPE` selectors, local Downloads import, read-only OpenNeuro context window, task-aware input slots, and drag targets for single EEG, athlete, or team processing.
2. **Analysis**: queued/running/completed jobs; direct links to the original generated pipeline HTML reports for GENERAL, ODDBALL, MOTOR, SLEEP, and longitudinal athlete comparisons; team-batch links to each completed athlete's report. The website no longer rebuilds a truncated results preview.
3. **Advanced Analysis**: draggable/selectable team and athlete result packages, local JSON preview/download, and an explicitly disabled future AI-processing action. No AI model has been connected.

## Coach workflow

1. Choose a **Test Type** (Oddball, Sleep, Motor-imagery, Unspecified) at the top. Choose **File Type** (Baseline or Testing).
2. `+ New Team`. Within its folder, `+ Add Athlete`. Every new athlete is initialized with **three empty Baseline shelves and one empty Testing shelf**, inheriting the currently selected Test Type.
3. Click **Open** or the gear on any shelf. The top selectors will reflect that shelf, and editing the selectors updates its test type and classification on the backend.
4. Add a primary EEG signal through its **+ Add EEG** button, or use **+ Import an EEG File** at the end of the athlete folder, then choose **Downloads**. The latter creates a new shelf on successful file selection; it does not replace one of the four initial empty shelves.
5. As soon as a `.set` is uploaded, a **`.fdt` companion slot** appears. Use it *only* when the `.set` references external `.fdt` sample data. For BrainVision `.vhdr`, `.eeg` and `.vmrk` companion slots appear. For Oddball and Motor-imagery, a task-event/annotation **object slot** appears; for Sleep, stage annotations can be added; for Unspecified there is no task-object slot. `object` is a UI role, **not a `.object` file format**.
6. Drag a populated EEG shelf to the processing window in Single EEG mode. Alternatively select **Test Athlete** and drag an athlete; the backend requires >=3 *uploaded*, task-compatible Baseline EEG shelves and >=1 uploaded Testing EEG. **Test Team** runs a separate comparison for each eligible athlete in the chosen task; ineligible athletes get explicit skipped reasons.
7. View the actual optimized-pipeline results in Analysis, and drag prepared scientific result packages in Advanced Analysis. Local reports are preserved.

### Accepted inputs and important limitations

- Primary EEG: `.set`, `.edf`, `.bdf`, `.vhdr`, `.fif`, `.fif.gz` (one primary per shelf).
- Required-if-referenced companions: `.fdt` for external EEGLAB data, `.eeg` and `.vmrk` for BrainVision.
- Events, scored stages and metadata sidecars: `.tsv`, `.csv`, `.json`, `.txt` as **auxiliary data**, not as standalone raw EEG signals.
- Oddball requires identifiable target/standard events for valid ERP/P300 results. Motor-imagery requires verified motor cues and appropriate EEG channels for ERD/ERS. Sleep analysis benefits from supplied scoring or optional YASA. Unspecified produces general EEG statistics. **A menu choice does not override evidence-based scientific routing.** If it disagrees with the detected task, the single-run result shows a warning.
- The browser **cannot force** the operating system to open the Downloads directory. The Downloads action opens a single native file picker immediately. If an upload fails, the import dialog shows the reason and offers Retry without reselecting the file. The coach can browse Downloads manually if the OS opens a different location.
- The OpenNeuro Connector browses a published snapshot and, from one **Download** on a supported EEG signal, resolves the BIDS bundle and imports it into the selected EEG shelf. Downloads still imports a local file. GraphQL variables use `ID!` for dataset and snapshot ids. Remote files are fetched only from `urls` returned for that dataset on `openneuro.org` or `s3.amazonaws.com/openneuro.org`. See `docs/openneuro-import-design.md` in the project handoff for the download decision, task rules, and what was verified live.
- The optimized artifact detector is explicitly experimental and produces review flags; it does not remove EEG data or establish diagnoses/athletic readiness.
- The prototype is local-only and does **not** include production authentication, encryption, cloud database or medical-device validation.

## Persistence and processing architecture

- `backend/app.py`: original FastAPI server, local SQLite connection, file storage, job records, artifact serving and legacy API compatibility.
- `backend/shelves.py`: additive schema migration, real central Repository endpoints, upload/validation logic, batched local athlete and team analysis, and read-only OpenNeuro GraphQL proxy.
- `neurobuddy_v2/`: optimized v0.7.1 scientific engine. **The one targeted comparative fix is forwarding the requested artifact/mains settings to both baseline and testing recordings**. Calculations are otherwise retained from the optimized pipeline.
- `v2/shelf-ui.js`: component-free dynamic shelf tree, task-aware file slots, Downloads/import dialog, OpenNeuro viewer, persistent actions and drag sources.
- `v2/app.js`: original three views, processing drop target, scientific report views and Advanced Analysis package selection.
- `v2/styles.css`: the pre-Repository dark theme and new shelf components.

A shelf uses a stable UUID in the existing `recordings` table (added `task_type`, `origin`, `dataset_ref` columns). Child `recording_files` records reference real data under `data/recordings/<shelf uuid>/`. Teams, athletes and jobs continue to use original tables. Existing databases are migrated additively, not reset. Run tasks use `ThreadPoolExecutor(max_workers=1)` to control peak memory; a single Team job processes eligible athletes sequentially, with results kept separate.

## New REST endpoints

| Action | Route |
|---|---|
| Library hierarchy | `GET /api/v2/shelf-library` |
| Create Team | `POST /api/v2/shelf-teams` |
| Delete Team | `DELETE /api/v2/shelf-teams/{team_id}` |
| Create Athlete + four shelves | `POST /api/v2/shelf-teams/{team_id}/athletes?task_type=oddball` |
| Delete Athlete | `DELETE /api/v2/shelf-athletes/{athlete_id}` |
| Add shelf | `POST /api/v2/shelf-athletes/{athlete_id}/shelves` |
| Change shelf type/class | `PATCH /api/v2/shelves/{shelf_id}` |
| Delete shelf | `DELETE /api/v2/shelves/{shelf_id}` |
| Upload individual signal/companion/events slot | `POST /api/v2/shelves/{shelf_id}/files` (multipart) |
| Delete a file | `DELETE /api/v2/shelves/{shelf_id}/files/{file_id}` |
| Run single/athlete/team analysis | `POST /api/v2/shelf-jobs` |
| Job result | `GET /api/v2/jobs/{job_id}` |
| Artifact download | `GET /api/v2/artifacts/{job_id}/{path}` |
| Advanced reports index (including team batch) | `GET /api/v2/shelf-advanced` |
| OpenNeuro snapshot | `GET /api/v2/openneuro/{dataset_id}` |
| OpenNeuro folder tree | `GET /api/v2/openneuro/{dataset_id}/tree?tag=1.0.0&tree=<id>` |
| Resolve one recording's bundle without downloading the signal | `POST /api/v2/openneuro/resolve-recording` |
| Import that bundle into a shelf | `POST /api/v2/openneuro/import-recording` |
| Import progress | `GET /api/v2/import-jobs/{job_id}` |
| Cancel or retry an import | `POST /api/v2/import-jobs/{job_id}/cancel` and `POST /api/v2/import-jobs/{job_id}/retry` |

FastAPI's own API documentation is at `/docs`.

## Testing

```bash
python -m pytest -q tests/
```

Latest project verification: **81 passed, 3 skipped**, plus one pre-existing failure in `tests/scientific/test_optimization_equivalence.py::test_batched_line_handles_nonfinite_and_unassessable` (a float mismatch under NumPy 2.5.5; the scientific engine was not edited to chase it). With `NEUROBUDDY_LIVE_OPENNEURO=1`, `tests/test_openneuro_live.py` passed: snapshot and tree reads, task resolution for ds003061, ds002336, and ds007181, and a full ds003061 download that v0.7.1 classified as oddball. A separate Chromium end-to-end test opened one native picker, selected a `.fif` file once, uploaded it to a real shelf, analyzed it through v0.7.1, and verified its generated HTML report returned HTTP 200. This includes original coach integration tests, new shelf CRUD/upload/comparison/team-batch/connector mocked API tests, and the optimized pipeline's scientific regression suite. The three skipped tests require unavailable real-data fixtures. Scientific processing was also verified on a synthetic EEGLAB `.set` and `.fif` recordings. A Chromium GUI test verified team and athlete creation, shelf creation, task-selection behavior, import dialog and tab navigation without JS exceptions.

Screenshots: `Screenshot_Dataset_Library.png` and `Screenshot_Analysis.png` show the corrected actual UI. Other screenshots include `Screenshot_Import_Menu.png`, `Screenshot_OpenNeuro_Connector.png`, and `Screenshot_Advanced.png`. The `.set` visible in the screenshot is a **valid synthetic demonstration recording**, not athlete data. The connector screenshot shows only the input viewer, not a live loaded dataset.

## Remaining development priorities

- End-to-end public OpenNeuro import is implemented for one selected EEG plus its resolved companions. Re-check live transfers when OpenNeuro changes snapshot layouts. The running app does not start analysis automatically after import.
- Dynamic completeness checks for embedded event markers, `.fdt` external pointers and BrainVision companions, rather than depending on later pipeline failure.
- Formal per-experiment quality/eligibility policies, including channels and events, before claiming a valid task-specific metric.
- Full integration of scientific provenance, clinical validation, authentication, user management and encrypted production data storage.

See `docs/FRONTEND_IMPLEMENTATION_PLAN.md` for detailed phased Cursor milestones.

## v0.3.1 website corrections

- **Downloads:** Removed the mixed `showOpenFilePicker()`/`input.click()` fallback. A single native `<input type="file">` opens synchronously from the user action. One selection starts upload; server errors appear inside the modal, and Retry reuses the selected File objects without requiring another trip through the file picker. The component preserves the newly created shelf ID if an upload fails, preventing duplicate shelves when retrying.
- **Shelf controls:** Removed the redundant `Select Shelf` button from the shelf footer. The shelf header's **Open** and gear controls still select shelves. Drag / Test EEG, add-file slots, task classification, and deletion are preserved.
- **Analysis:** Removed the re-created, truncated JSON metric/figure preview. Each completed single EEG run links directly to its real `report.html`; each longitudinal run links to `athlete_report.html` and to its individual baseline/test HTML reports, with original ZIP/CSV/JSON downloads; team batches link to each completed athlete's HTML report. The scientific reports and backend artifact-serving endpoint are unchanged.
- **Scope:** No scientific engine modules, SQLite schema or API endpoints were changed in v0.3.1. The central three-tab layout, uploads of companion/event files, longitudinal strict compatibility checks, Advanced Analysis packages, and read-only OpenNeuro browsing remain as before.
