# Neurobuddy Coach — architecture audit (for the demo site)

This audit is based on a read-only inspection of the supplied Coach archive (`Neurobuddy_Coach_current.zip`) extracted to a working folder. **No files under `backend/` or `neurobuddy_v2/` were edited, moved, reformatted, or imported into this demo.** The demonstration website in `demo-site/` is a separate React app driven by local fixture data.

Inspected: `Index.html`, `v2/app.js`, `v2/shelf-ui.js`, `v2/styles.css`, `README.md`, `neurobuddy_v2/analysis.py`, `neurobuddy_v2/comparative.py`, `neurobuddy_v2/artifact_detection.py`, `neurobuddy_v2/interactive_views.py`, `v2/assets/cyber-neuron.png`, `v2/videos/all-tests.mp4`, and `Screenshot_*.png`. Supporting context: `neurobuddy_v2/__init__.py` (`0.7.1-optimized`), `neurobuddy_v2/routing.py`, `backend/app.py` (`ThreadPoolExecutor(max_workers=1)`), and `docs/FRONTEND_IMPLEMENTATION_PLAN.md`.

## Product shape (verified)

The running Coach app is a **three-view vanilla HTML/JS workspace** served by FastAPI, not a React SPA.

1. **Dataset Library** — central Repository: Team → Athlete → EEG shelves. Global `TEST TYPE` and `FILE TYPE` selectors. Task-aware file slots. Drag (or keyboard Select) into Single EEG / Test Athlete / Test Team processing.
2. **Analysis** — job list with links to the **original generated pipeline HTML**, plus ZIP/CSV/JSON artifacts. The v0.3.1 UI no longer rebuilds a truncated in-page scientific preview.
3. **Advanced Analysis** — selectable/draggable team and athlete **result packages**, local JSON preview/download. **AI interpretation is not connected.**

Scientific engine: **Neurobuddy v0.7.1 optimized** (`neurobuddy_v2/__init__.py`). Persistence: local SQLite + files under `data/`. Prototype is local-only; no production auth, encryption, or medical-device validation.

## Verified capabilities

### Library and intake

- Create/delete teams; create/delete athletes; add/delete shelves; PATCH shelf `task_type` / `classification`.
- New athlete is initialized with **three empty Baseline shelves and one empty Testing shelf** inheriting the currently selected test type. Empty placeholders are **not** baseline evidence.
- `+ Import an EEG File` at the athlete folder creates a **new** shelf on successful selection; it does not fill one of the four initial empty shelves.
- Primary EEG (one per shelf): `.set`, `.edf`, `.bdf`, `.vhdr`, `.fif`, `.fif.gz`.
- Companion slots are **conditional, not automatic for every format**:
  - `.set` → optional `.fdt` slot, required only if the `.set` references external sample data.
  - `.vhdr` → `.eeg` / `.vmrk` companion slots.
- Task object / events slots:
  - Oddball and Motor-imagery: events/annotations object.
  - Sleep: optional stage annotations.
  - Unspecified: no required task object.
- Auxiliary `.tsv` / `.csv` / `.json` / `.txt` are **not** standalone raw EEG.
- Native `<input type="file">` for local import (v0.3.1); browser cannot force the OS Downloads folder.
- OpenNeuro: read-only snapshot browser (dataset → nested folders), metadata preview, per-file Download of a supported EEG signal, **separate** “Add this TSV” and “Add this .fdt” actions. BIDS bundle resolution exists on the backend (`resolve-recording` / `import-recording`). GraphQL/S3 traffic is server-side, not from this demo.

### Processing modes

- **Single EEG** — one ready (uploaded) shelf.
- **Athlete longitudinal** — current implementation: **Oddball: 2+ compatible baseline EEGs plus test**; **Sleep / Motor / Unspecified: 3+ plus test**. All scientific compatibility checks still apply (`comparative.baseline_minimum`).
- **Team** — eligible athletes processed **independently** (not pooled into one team baseline). Ineligible athletes are skipped with reasons. Sequential single worker (`max_workers=1`).

### Scientific routes (engine, not browser)

- Menu choice does **not** override evidence-based routing (`routing.decide`). Filename alone does not determine Oddball/Motor/Sleep.
- **Oddball**: stimulus-linked EEG; target/standard labels; P300/N200 and ERP **when usable event data exists**.
- **Motor imagery**: documented motor cues; mu/beta ERD/ERS near motor electrodes (e.g. C3/C4). Does **not** measure exertion or recovery readiness from EEG alone.
- **Sleep**: scored stages preferred; optional YASA estimation; hypnogram, durations, spectral features, candidate spindles/slow waves where prerequisites permit. Automatically staged results are **unreviewed**.
- **Unspecified / GENERAL**: channel statistics, frequency power, signal quality, Hjorth; no specialized events required.
- Longitudinal comparison consumes unchanged single-recording reports; z-score flag is **`|z| > 3`** (exactly 3 is within range). Comparison is blocked on protocol/identity issues (task family, sampling rate, channel-name sets, pipeline version, differing BIDS subject IDs, duplicate SHA-256, incomplete processing).
- Interactive report extras: brain activity player, comparison heatmap, sleep replay (`interactive_views.py`) — generated in the HTML report, not recomputed in the Coach browser.

### Artifact screening

- Experimental windowed detector (`artifact_detection.py`, `DETECTOR_VERSION = window-eeg-0.1.0`).
- Produces review flags / channel-level evidence. **Does not remove data, filter the waveform for “cleaning,” or diagnose.** Downstream features are unchanged.

## Honest limitations (do not over-claim in the demo)

- This demo website **does not** run Python, FastAPI, SQLite, MNE, or any EEG pipeline.
- **AI interpretation is planned / not connected.** There is no chatbot that has analyzed EEG.
- Automatic companion-file import is **not universally complete**. Current UI treats companion and TSV selection as **separate actions**. Backend bundle resolution exists; the demo must label any “auto-collect companions” animation as **planned / conceptual**.
- OpenNeuro availability depends on dataset structure and format. The demo must not iframe or call the OpenNeuro API. The connector screenshot in the archive shows the **input viewer**, not a live loaded dataset.
- Artifact flags are candidates, not cleaned EEG and not clinical findings.
- Team results are per-athlete; the research prototype uses a **constrained single worker**.
- Empty shelves are placeholders. Counting them as completed baselines is forbidden.
- No medical diagnoses, validated fatigue/recovery scores, real-time EEG, production auth, or encrypted multi-user storage.
- IONM grading, SNR proxies, and similar metrics in the engine are unvalidated heuristics (engine warnings).

## Visual language to reuse (not copy as a SaaS clone)

Coach UI: midnight navy (`#0b1020` / `#0d1426` / `#121a2e`), lavender accent (`#8b88ff`), teal status (`#45dac5`), danger pink (`#ff909b`), 1px borders, 18px-ish cards, Inter-like UI sans, cyber-neuron mark on an **off-white** stage with a **red axonal pulse**. Three-tab sidebar, workflow toolbar, dashed drop zones.

The demo site follows the brief’s refined palette (`#0A1020`, `#101B30`, ivory `#F5F1E9`, teal `#59CEC6`, lavender `#A59BFF`, axon red `#ED4658`) and editorial cinematic layouts rather than cloning the Coach chrome.
