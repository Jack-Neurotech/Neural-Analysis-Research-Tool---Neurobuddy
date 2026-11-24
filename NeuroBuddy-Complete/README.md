# NeuroBuddy Complete — demo + functional Coach

Both original applications are included. The demo is React/Vite; Coach is the actual FastAPI/MNE Python application with its original scientific engine. No simulated analysis has been substituted.

## Mac / VS Code
Prerequisites: Python 3.11 or 3.12 recommended, Node.js 22.12+ or 24 LTS, npm, internet access for first dependency installation. From this extracted folder run:

```sh
bash start.command
```

The script installs dependencies, starts both local services, checks readiness, and opens the demo in your browser. Keep the terminal open. Ctrl+C stops both. If either port is already used, stop the old server first. If you are inside VS Code, use Simple Browser: Show with http://127.0.0.1:5173/ or use a normal browser.

The Try Neuro-Buddy button opens http://127.0.0.1:8765/#library. Coach persists data in neurobuddy-coach/data/ by default. Back up this directory. Optional sleep dependencies are described in the Coach README.

## Separate startup (if needed)
Terminal 1, from the package root:
```sh
cd neurobuddy-coach
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```
Terminal 2, from the package root:
```sh
cd demo-site
npm ci
npm run dev
```

## Distribution
This is a combined local package, not a Pyodide conversion or a public hosted URL. Recipients must install dependencies and run the launcher on their own computer. Do not expose the unauthenticated Coach backend to the public internet. For a future independently deployed Coach, set VITE_COACH_URL when building the demo.

## Verification
The Coach backend was launched in the packaging environment and its root, health and shelf-library endpoints returned HTTP 200. Original demo source and media are included. Full demo build and macOS launch were not verified in the packaging environment; npm dependency installation could not be completed there. Scientific algorithms were not changed or independently revalidated.
