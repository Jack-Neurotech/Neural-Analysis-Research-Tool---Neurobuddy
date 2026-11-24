# Neurobuddy cinematic demo

Standalone React + TypeScript + Vite tour of Neurobuddy Coach. All interactions use local fixture data. No Python, FastAPI, SQLite, OpenNeuro API, file uploads, or EEG processing.

## Launch

```bash
cd demo-site
npm install
npm run dev
```

Then open the printed local URL (typically `http://127.0.0.1:5173`).

```bash
npm run build
npm run preview
npm run test
```

## What this is

An 11-scene scrollytelling site for coaches, sports scientists, and collaborators. Interactive controls are labeled as an illustrative demo. Sample JSON/CSV downloads live in `public/demo-data/`. Bundled media is in `public/media/`.

See `ARCHITECTURE_AUDIT.md` for verified Coach capabilities and honest limitations.
