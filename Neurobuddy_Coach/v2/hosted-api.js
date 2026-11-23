/* Shareable-link adapter. If the FastAPI server is not running, the Coach UI
   keeps working from this browser with sample data so a published URL can be
   sent and clicked. Live uvicorn traffic is never intercepted. */
(() => {
  'use strict';
  const origFetch = window.fetch.bind(window);
  const KEY = 'neurobuddy-share-v1';
  const SIGNALS = ['.set', '.edf', '.bdf', '.vhdr', '.fif', '.fif.gz'];
  const TASKS = ['oddball', 'motor', 'sleep', 'unspecified'];
  const TYPES = ['baseline', 'testing'];
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const isSignal = (n) => SIGNALS.some((ext) => String(n || '').toLowerCase().endsWith(ext));
  const now = () => new Date().toISOString();
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  }));
  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'private, no-store' }
  });
  const fail = (status, detail) => json({ detail }, status);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  const TEAM = '11111111-1111-4111-8111-111111111111';
  const ATHLETE = '22222222-2222-4222-8222-222222222222';
  const SHELVES = [
    '33333333-3333-4333-8333-333333333331',
    '33333333-3333-4333-8333-333333333332',
    '33333333-3333-4333-8333-333333333333',
    '33333333-3333-4333-8333-333333333334'
  ];
  const JOB = '44444444-4444-4444-8444-444444444444';
  const FILES = [
    '55555555-5555-4555-8555-555555555551',
    '55555555-5555-4555-8555-555555555552',
    '55555555-5555-4555-8555-555555555553',
    '55555555-5555-4555-8555-555555555554'
  ];

  function emptyStore() {
    const created = now();
    const shelves = [
      { id: SHELVES[0], athlete_id: ATHLETE, classification: 'baseline', source_name: 'sub-alex_ses-01_task-rest_eeg.fif', directory: SHELVES[0], created_at: created, task_type: 'unspecified', origin: 'sample' },
      { id: SHELVES[1], athlete_id: ATHLETE, classification: 'baseline', source_name: 'sub-alex_ses-02_task-rest_eeg.fif', directory: SHELVES[1], created_at: created, task_type: 'unspecified', origin: 'sample' },
      { id: SHELVES[2], athlete_id: ATHLETE, classification: 'baseline', source_name: 'sub-alex_ses-03_task-rest_eeg.fif', directory: SHELVES[2], created_at: created, task_type: 'unspecified', origin: 'sample' },
      { id: SHELVES[3], athlete_id: ATHLETE, classification: 'testing', source_name: 'sub-alex_ses-04_task-test_eeg.fif', directory: SHELVES[3], created_at: created, task_type: 'unspecified', origin: 'sample' }
    ];
    const files = shelves.map((shelf, i) => ({
      id: FILES[i], recording_id: shelf.id, name: shelf.source_name, size_bytes: 184320 + i * 4096
    }));
    const analysis = {
      pipeline_version: '0.7.1-optimized',
      processing_status: 'COMPLETE',
      classification: { task_family: 'unspecified' },
      provenance: { artifact_mode: 'experimental', shareable_demo: true }
    };
    const result = {
      mode: 'athlete',
      athlete_id: ATHLETE,
      team_id: TEAM,
      task_type: 'unspecified',
      comparison: { metrics: [{ metric: 'shared.channel.C3.alpha_power', baseline_mean: 12.4, test_value: 13.1, z: 0.42, flag: 'Within range' }] },
      baseline: { baseline_recording_count: 3 },
      individual: [
        { classification: 'baseline', result: analysis, entrypoint: 'baseline/0/report.html' },
        { classification: 'baseline', result: analysis, entrypoint: 'baseline/1/report.html' },
        { classification: 'baseline', result: analysis, entrypoint: 'baseline/2/report.html' },
        { classification: 'testing', result: analysis, entrypoint: 'test/report.html' }
      ],
      summary: { status: 'COMPLETE', note: 'Sample shareable report. Full MNE analysis runs on the local Neurobuddy server.' },
      entrypoint: 'athlete_report.html',
      package: 'athlete_report.zip'
    };
    return {
      teams: [{ id: TEAM, name: 'Demo Track Club', created_at: created }],
      athletes: [{ id: ATHLETE, team_id: TEAM, name: 'Alex Rivera', created_at: created }],
      recordings: shelves,
      files,
      jobs: [{
        id: JOB, mode: 'athlete', target_id: ATHLETE, test_recording_id: SHELVES[3],
        created_at: created, updated_at: created, status: 'completed', error: null,
        result, result_dir: JOB, team_id: TEAM, athlete_id: ATHLETE
      }]
    };
  }

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && Array.isArray(parsed.teams) && Array.isArray(parsed.jobs)) return parsed;
      }
    } catch { /* use seed */ }
    const seeded = emptyStore();
    save(seeded);
    return seeded;
  }

  function save(db) {
    try { localStorage.setItem(KEY, JSON.stringify(db)); } catch { /* quota */ }
  }

  function find(db, table, id) {
    return (db[table] || []).find((row) => row.id === id) || null;
  }

  function must(db, table, id, label) {
    const row = find(db, table, id);
    if (!row) throw Object.assign(new Error(label + ' not found'), { status: 404 });
    return row;
  }

  function baselineMinimum(task) {
    return task === 'oddball' ? 2 : 3;
  }

  function library(db) {
    return {
      teams: db.teams.map((team) => ({
        ...team,
        athletes: db.athletes.filter((a) => a.team_id === team.id).map((athlete) => ({
          id: athlete.id, name: athlete.name, team_id: athlete.team_id, created_at: athlete.created_at,
          shelves: db.recordings.filter((r) => r.athlete_id === athlete.id).map((r) => {
            const files = db.files.filter((f) => f.recording_id === r.id).map((f) => ({
              id: f.id, name: f.name, size_bytes: f.size_bytes
            }));
            const ready = files.some((f) => isSignal(f.name));
            return {
              id: r.id, classification: r.classification, source_name: r.source_name,
              created_at: r.created_at, task_type: r.task_type, origin: r.origin || 'downloads',
              files, ready, task: { task: r.task_type, status: ready ? 'ready' : 'empty', warnings: [] }
            };
          })
        }))
      })),
      pipeline_version: '0.7.1-optimized',
      shareable: true
    };
  }

  function jobPublic(job, includeResult) {
    const row = {
      id: job.id, mode: job.mode, target_id: job.target_id, test_recording_id: job.test_recording_id,
      created_at: job.created_at, updated_at: job.updated_at, status: job.status, error: job.error,
      team_id: job.team_id, athlete_id: job.athlete_id
    };
    if (includeResult) row.result = job.result || null;
    return row;
  }

  function reportHtml(job, path) {
    const title = path.endsWith('athlete_report.html') ? 'Athlete comparison' : 'EEG report';
    const athlete = job.athlete_id ? job.athlete_id.slice(0, 8) : 'sample';
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Neurobuddy · ${esc(title)}</title>
<style>body{margin:0;font-family:Inter,system-ui,sans-serif;background:#0b1020;color:#f0f3fa;padding:32px}main{max-width:720px;margin:0 auto}a{color:#8b88ff}.chip{display:inline-block;background:#15372e;color:#90ead0;padding:6px 10px;border-radius:8px;font-size:12px}pre{background:#121a2e;border:1px solid #29354e;padding:16px;border-radius:12px;overflow:auto}</style></head>
<body><main><p class="chip">Shareable sample report</p>
<h1>${esc(title)}</h1>
<p>This HTML report opened from a link you can send. The hosted demo shows sample Neurobuddy v0.7.1 output. Full MNE processing runs on the local Coach server.</p>
<p>Job <code>${esc(job.id)}</code> · athlete ${esc(athlete)} · ${esc(path)}</p>
<pre>${esc(JSON.stringify(job.result && job.result.summary || { status: 'COMPLETE', pipeline: '0.7.1-optimized' }, null, 2))}</pre>
<p><a href="/">Open Neurobuddy Coach</a></p></main></body></html>`;
  }

  const blobs = new Map();
  function artifactUrl(id, path) {
    const db = load();
    const job = find(db, 'jobs', id);
    if (!job) return `/api/v2/artifacts/${encodeURIComponent(id)}/${path}`;
    const key = id + '/' + path;
    if (!blobs.has(key)) {
      const body = path.endsWith('.json')
        ? JSON.stringify(job.result || {}, null, 2)
        : path.endsWith('.csv')
          ? 'metric,baseline_mean,test_value,z,flag\nshared.channel.C3.alpha_power,12.4,13.1,0.42,Within range\n'
          : reportHtml(job, path);
      const type = path.endsWith('.json') ? 'application/json' : path.endsWith('.csv') ? 'text/csv' : 'text/html';
      blobs.set(key, URL.createObjectURL(new Blob([body], { type })));
    }
    return blobs.get(key);
  }

  function readyShelves(db, athleteId, task) {
    return db.recordings.filter((r) => r.athlete_id === athleteId && (!task || r.task_type === task) &&
      db.files.some((f) => f.recording_id === r.id && isSignal(f.name)));
  }

  function chooseComparison(db, athleteId, task, selectedTest) {
    const records = readyShelves(db, athleteId, task);
    const tests = records.filter((r) => r.classification === 'testing');
    const test = selectedTest ? tests.find((r) => r.id === selectedTest) : tests[tests.length - 1];
    if (!test) throw Object.assign(new Error('Upload at least one Testing EEG for the selected task.'), { status: 422 });
    const usedTask = test.task_type;
    const bases = records.filter((r) => r.classification === 'baseline' && r.task_type === usedTask);
    const needed = baselineMinimum(usedTask);
    if (bases.length < needed) {
      throw Object.assign(new Error(`At least ${needed} uploaded Baseline EEG shelves with the same Test Type (${usedTask}) are needed; found ${bases.length}.`), { status: 422 });
    }
    return { bases, test };
  }

  function sampleAnalysis() {
    return {
      pipeline_version: '0.7.1-optimized',
      processing_status: 'COMPLETE',
      classification: { task_family: 'unspecified' },
      provenance: { artifact_mode: 'experimental', shareable_demo: true }
    };
  }

  function runSingle(rec) {
    return {
      mode: 'single', recording_id: rec.id, analysis: sampleAnalysis(),
      task_selected: rec.task_type, task_detected: 'unspecified', task_warning: null,
      entrypoint: 'report.html', package: 'report.zip'
    };
  }

  function runAthlete(db, athlete, task, testId) {
    const { bases, test } = chooseComparison(db, athlete.id, task, testId);
    const analysis = sampleAnalysis();
    return {
      mode: 'athlete', athlete_id: athlete.id, team_id: athlete.team_id, task_type: test.task_type,
      comparison: { metrics: [{ metric: 'shared.channel.C3.alpha_power', baseline_mean: 12.4, test_value: 13.1, z: 0.42, flag: 'Within range' }] },
      baseline: { baseline_recording_count: bases.length },
      individual: [
        ...bases.map((_, i) => ({ classification: 'baseline', result: analysis, entrypoint: `baseline/${i}/report.html` })),
        { classification: 'testing', result: analysis, entrypoint: 'test/report.html' }
      ],
      summary: { status: 'COMPLETE', note: 'Sample shareable report generated in the browser.' },
      entrypoint: 'athlete_report.html', package: 'athlete_report.zip'
    };
  }

  function createShelves(db, athleteId, task) {
    for (const classification of ['baseline', 'baseline', 'baseline', 'testing']) {
      db.recordings.push({
        id: uid(), athlete_id: athleteId, classification, source_name: '', directory: uid(),
        created_at: now(), task_type: task, origin: 'downloads'
      });
    }
  }

  async function readJson(init) {
    if (!init || !init.body) return {};
    if (typeof init.body === 'string') return JSON.parse(init.body || '{}');
    if (init.body instanceof Blob) return JSON.parse(await init.body.text() || '{}');
    return {};
  }

  async function fileNames(init) {
    const body = init && init.body;
    if (body && typeof FormData !== 'undefined' && body instanceof FormData) {
      const names = [];
      for (const [, value] of body.entries()) {
        if (value && typeof value === 'object' && 'name' in value) names.push(value.name);
      }
      return { slot: body.get('slot') || 'signal', names, sizes: names.map(() => 2048) };
    }
    return { slot: 'signal', names: [], sizes: [] };
  }

  function route(pathname) {
    const path = pathname.replace(/^\/api/, '');
    return path;
  }

  async function handle(url, init) {
    const method = (init && init.method || 'GET').toUpperCase();
    const parsed = new URL(url, location.origin);
    const path = route(parsed.pathname);
    const db = load();
    try {
      if (method === 'GET' && path === '/v2/health') {
        return json({
          ok: true, engine: 'Neurobuddy v0.7.1', pipeline_version: '0.7.1-optimized',
          mode: 'shareable-link', ai_connected: false, repository_connected: true, sample_data: true
        });
      }
      if (method === 'GET' && path === '/v2/shelf-library') return json(library(db));
      if (method === 'GET' && path === '/v2/jobs') return json({ jobs: db.jobs.map((j) => jobPublic(j, false)) });
      if (method === 'GET' && path === '/v2/shelf-advanced') {
        const groups = [];
        for (const team of db.teams) {
          const members = [];
          for (const athlete of db.athletes.filter((a) => a.team_id === team.id)) {
            const reports = [];
            for (const job of db.jobs.filter((j) => j.status === 'completed')) {
              if ((job.mode === 'single' || job.mode === 'athlete') && job.athlete_id === athlete.id) {
                reports.push({ id: job.id, mode: job.mode, created_at: job.created_at, member_athlete_id: null });
              } else if (job.mode === 'team' && job.team_id === team.id && job.result) {
                if ((job.result.members || []).some((m) => m.status === 'completed' && m.athlete_id === athlete.id)) {
                  reports.push({ id: job.id, mode: 'team', created_at: job.created_at, member_athlete_id: athlete.id });
                }
              }
            }
            const shelves = db.recordings.filter((r) => r.athlete_id === athlete.id).map((r) => {
              const files = db.files.filter((f) => f.recording_id === r.id);
              return {
                id: r.id, classification: r.classification, task_type: r.task_type,
                source_name: r.source_name || '', file_count: files.length,
                bytes: files.reduce((n, f) => n + (f.size_bytes || 0), 0)
              };
            });
            if (reports.length) members.push({ id: athlete.id, name: athlete.name, reports, shelves });
          }
          if (members.length) groups.push({ id: team.id, name: team.name, athletes: members });
        }
        return json({ teams: groups, ai_connected: false, pipeline_version: '0.7.1-optimized' });
      }

      let m = path.match(/^\/v2\/jobs\/([^/]+)$/);
      if (m && method === 'GET') {
        if (!UUID.test(m[1])) return fail(422, 'Unknown analysis report.');
        return json(jobPublic(must(db, 'jobs', m[1], 'Job'), true));
      }
      if (m && method === 'DELETE') {
        if (!UUID.test(m[1])) return fail(422, 'Unknown analysis report.');
        const athleteId = parsed.searchParams.get('athlete_id');
        const job = must(db, 'jobs', m[1], 'Job');
        if (job.status === 'queued' || job.status === 'running') return fail(409, 'Wait until this analysis finishes before deleting it.');
        if (athleteId) {
          if (job.mode !== 'team') return fail(422, 'This report is not a team batch. Delete the report itself.');
          const members = [...(job.result && job.result.members || [])];
          if (!members.some((row) => row.athlete_id === athleteId)) return fail(404, 'Athlete report not found.');
          const kept = members.filter((row) => row.athlete_id !== athleteId);
          if (kept.length) {
            job.result = { ...job.result, members: kept };
            job.updated_at = now();
            save(db);
            return json({ deleted: true, id: job.id, athlete_id: athleteId, removed: 'athlete' });
          }
        }
        db.jobs = db.jobs.filter((row) => row.id !== job.id);
        save(db);
        return json({ deleted: true, id: job.id, removed: 'job' });
      }

      m = path.match(/^\/v2\/jobs\/([^/]+)\/retry$/);
      if (m && method === 'POST') {
        const job = must(db, 'jobs', m[1], 'Job');
        if (!['failed', 'interrupted'].includes(job.status)) return fail(409, 'Only failed or interrupted jobs can be retried.');
        return handle(new URL('/api/v2/shelf-jobs', location.origin).href, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: job.mode, target_id: job.target_id, test_recording_id: job.test_recording_id })
        });
      }

      if (method === 'POST' && path === '/v2/shelf-teams') {
        const body = await readJson(init);
        const name = String(body.name || '').trim();
        if (!name) return fail(422, 'Team name is required.');
        const row = { id: uid(), name, created_at: now() };
        db.teams.push(row); save(db);
        return json(row, 201);
      }

      m = path.match(/^\/v2\/shelf-teams\/([^/]+)\/athletes$/);
      if (m && method === 'POST') {
        must(db, 'teams', m[1], 'Team');
        const task = parsed.searchParams.get('task_type') || 'unspecified';
        if (!TASKS.includes(task)) return fail(422, 'Test Type must be Oddball, Motor-imagery, Sleep, or Unspecified.');
        const body = await readJson(init);
        const name = String(body.name || '').trim();
        if (!name) return fail(422, 'Athlete name is required.');
        const row = { id: uid(), team_id: m[1], name, created_at: now() };
        db.athletes.push(row);
        createShelves(db, row.id, task);
        save(db);
        return json({ id: row.id, team_id: m[1], name, created_shelves: 4 }, 201);
      }

      m = path.match(/^\/v2\/shelf-teams\/([^/]+)$/);
      if (m && method === 'DELETE') {
        must(db, 'teams', m[1], 'Team');
        const aids = db.athletes.filter((a) => a.team_id === m[1]).map((a) => a.id);
        const rids = db.recordings.filter((r) => aids.includes(r.athlete_id)).map((r) => r.id);
        db.files = db.files.filter((f) => !rids.includes(f.recording_id));
        db.recordings = db.recordings.filter((r) => !aids.includes(r.athlete_id));
        db.athletes = db.athletes.filter((a) => a.team_id !== m[1]);
        db.teams = db.teams.filter((t) => t.id !== m[1]);
        save(db);
        return json({ deleted: true, id: m[1] });
      }

      m = path.match(/^\/v2\/shelf-athletes\/([^/]+)\/shelves$/);
      if (m && method === 'POST') {
        must(db, 'athletes', m[1], 'Athlete');
        const body = await readJson(init);
        const task = body.task_type || 'unspecified';
        const kind = body.classification || 'baseline';
        if (!TASKS.includes(task)) return fail(422, 'Test Type must be Oddball, Motor-imagery, Sleep, or Unspecified.');
        if (!TYPES.includes(kind)) return fail(422, 'File Type must be Baseline or Testing.');
        const row = {
          id: uid(), athlete_id: m[1], classification: kind, source_name: '', directory: uid(),
          created_at: now(), task_type: task, origin: 'downloads'
        };
        db.recordings.push(row); save(db);
        return json({ id: row.id, task_type: task, classification: kind }, 201);
      }

      m = path.match(/^\/v2\/shelf-athletes\/([^/]+)$/);
      if (m && method === 'DELETE') {
        must(db, 'athletes', m[1], 'Athlete');
        const rids = db.recordings.filter((r) => r.athlete_id === m[1]).map((r) => r.id);
        db.files = db.files.filter((f) => !rids.includes(f.recording_id));
        db.recordings = db.recordings.filter((r) => r.athlete_id !== m[1]);
        db.athletes = db.athletes.filter((a) => a.id !== m[1]);
        save(db);
        return json({ deleted: true, id: m[1] });
      }

      m = path.match(/^\/v2\/shelves\/([^/]+)$/);
      if (m && method === 'PATCH') {
        const shelf = must(db, 'recordings', m[1], 'Recording');
        const body = await readJson(init);
        const changes = { id: shelf.id };
        if (body.task_type != null) {
          if (!TASKS.includes(body.task_type)) return fail(422, 'Test Type must be Oddball, Motor-imagery, Sleep, or Unspecified.');
          shelf.task_type = body.task_type; changes.task_type = body.task_type;
        }
        if (body.classification != null) {
          if (!TYPES.includes(body.classification)) return fail(422, 'File Type must be Baseline or Testing.');
          shelf.classification = body.classification; changes.classification = body.classification;
        }
        save(db);
        return json(changes);
      }
      if (m && method === 'DELETE') {
        must(db, 'recordings', m[1], 'Recording');
        db.files = db.files.filter((f) => f.recording_id !== m[1]);
        db.recordings = db.recordings.filter((r) => r.id !== m[1]);
        save(db);
        return json({ deleted: true, id: m[1] });
      }

      m = path.match(/^\/v2\/shelves\/([^/]+)\/files\/([^/]+)$/);
      if (m && method === 'DELETE') {
        const shelf = must(db, 'recordings', m[1], 'Recording');
        const file = db.files.find((f) => f.id === m[2] && f.recording_id === m[1]);
        if (!file) return fail(404, 'File not in EEG shelf.');
        db.files = db.files.filter((f) => f.id !== file.id);
        const remains = db.files.filter((f) => f.recording_id === shelf.id).map((f) => f.name);
        shelf.source_name = remains.find(isSignal) || '';
        save(db);
        return json({ deleted: true });
      }

      m = path.match(/^\/v2\/shelves\/([^/]+)\/files$/);
      if (m && method === 'POST') {
        const shelf = must(db, 'recordings', m[1], 'Recording');
        const { slot, names, sizes } = await fileNames(init);
        if (!['signal', 'companion', 'events'].includes(slot)) return fail(422, 'Select signal, companion, or events.');
        const existing = db.files.filter((f) => f.recording_id === shelf.id).map((f) => f.name);
        let useNames = names.filter(Boolean);
        if (!useNames.length) useNames = [slot === 'signal' ? 'uploaded-demo.fif' : slot === 'events' ? 'events.tsv' : 'companion.fdt'];
        if (slot === 'signal' && useNames.some((n) => !isSignal(n))) return fail(422, 'The signal slot accepts .set, .edf, .bdf, .vhdr, .fif or .fif.gz only.');
        if (existing.some((n) => useNames.some((x) => x.toLowerCase() === n.toLowerCase()))) {
          return fail(409, 'That file already exists in this EEG shelf. Remove it first to replace.');
        }
        if (existing.filter(isSignal).length + useNames.filter(isSignal).length > 1) {
          return fail(422, 'Each EEG shelf holds one signal recording. Add a second shelf for another EEG.');
        }
        useNames.forEach((name, i) => {
          db.files.push({ id: uid(), recording_id: shelf.id, name, size_bytes: sizes[i] || 2048 });
        });
        const all = db.files.filter((f) => f.recording_id === shelf.id).map((f) => f.name);
        shelf.source_name = all.find(isSignal) || shelf.source_name;
        save(db);
        return json({ id: shelf.id, uploaded: useNames, file_count: all.length }, 201);
      }

      if (method === 'POST' && path === '/v2/shelf-jobs') {
        const req = await readJson(init);
        if (!['single', 'athlete', 'team'].includes(req.mode)) return fail(422, 'Select Single EEG, Test Athlete, or Test Team.');
        let athleteId = null, teamId = null, result, status = 'completed', error = null;
        if (req.mode === 'single') {
          const rec = must(db, 'recordings', req.target_id, 'Recording');
          if (!rec.source_name) return fail(422, 'Upload an EEG signal to this shelf first.');
          const athlete = must(db, 'athletes', rec.athlete_id, 'Athlete');
          athleteId = athlete.id; teamId = athlete.team_id;
          result = runSingle(rec);
        } else if (req.mode === 'athlete') {
          const athlete = must(db, 'athletes', req.target_id, 'Athlete');
          athleteId = athlete.id; teamId = athlete.team_id;
          try { result = runAthlete(db, athlete, req.task_type, req.test_recording_id); }
          catch (err) { return fail(err.status || 422, err.message); }
        } else {
          const team = must(db, 'teams', req.target_id, 'Team');
          teamId = team.id;
          const members = [];
          for (const athlete of db.athletes.filter((a) => a.team_id === team.id)) {
            try {
              const one = runAthlete(db, athlete, req.task_type, null);
              members.push({
                athlete_id: athlete.id, athlete_name: athlete.name, status: 'completed',
                relative_report: `athletes/${athlete.id}/athlete_report.html`, result: one
              });
            } catch (err) {
              members.push({ athlete_id: athlete.id, athlete_name: athlete.name, status: 'skipped', message: err.message });
            }
          }
          if (!members.some((row) => row.status === 'completed')) {
            return fail(422, 'No athletes have enough compatible uploaded baseline EEGs and 1 testing EEG for this task. Oddball needs 2 baselines; sleep, motor, and unspecified need 3.');
          }
          result = { mode: 'team', team_id: team.id, members, task_type: req.task_type, entrypoint: null };
        }
        const job = {
          id: uid(), mode: req.mode, target_id: req.target_id, test_recording_id: req.test_recording_id || null,
          created_at: now(), updated_at: now(), status, error, result, result_dir: uid(),
          team_id: teamId, athlete_id: athleteId
        };
        db.jobs.unshift(job); save(db);
        return json({ id: job.id, status: 'queued', mode: req.mode }, 202);
      }

      m = path.match(/^\/v2\/artifacts\/([^/]+)\/(.+)$/);
      if (m && method === 'GET') {
        const job = must(db, 'jobs', m[1], 'Job');
        const pathName = decodeURIComponent(m[2]);
        const body = pathName.endsWith('.json')
          ? JSON.stringify(job.result || {}, null, 2)
          : pathName.endsWith('.csv')
            ? 'metric,baseline_mean,test_value,z,flag\nshared.channel.C3.alpha_power,12.4,13.1,0.42,Within range\n'
            : reportHtml(job, pathName);
        const type = pathName.endsWith('.json') ? 'application/json' : pathName.endsWith('.csv') ? 'text/csv' : 'text/html; charset=utf-8';
        return new Response(body, { status: 200, headers: { 'content-type': type, 'cache-control': 'private, no-store' } });
      }

      if (path.startsWith('/v2/openneuro') || path.startsWith('/v2/import-jobs')) {
        return fail(501, 'OpenNeuro import stays on the local Neurobuddy server. This shareable link runs the Coach UI with sample data.');
      }

      return fail(404, 'The EEG API endpoint ' + path + ' is not available on this shareable link.');
    } catch (err) {
      return fail(err.status || 400, err.message || 'Request failed');
    }
  }

  const ready = origFetch('/api/v2/health', { cache: 'no-store' }).then(async (response) => {
    if (!response.ok) return 'share';
    try {
      const payload = await response.clone().json();
      if (payload && payload.ok && payload.mode !== 'shareable-link') return 'live';
    } catch { /* not JSON */ }
    return response.ok ? 'live' : 'share';
  }).catch(() => 'share');

  window.fetch = async function (input, init) {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    if (!url.includes('/api/')) return origFetch(input, init);
    const mode = await ready;
    if (mode === 'live') return origFetch(input, init);
    return handle(url, init || {});
  };

  const share = {
    mode: 'unknown',
    modePromise: ready,
    artifactUrl,
    copyLink() {
      const link = location.origin + location.pathname + location.search;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(link).then(() => link).catch(() => {
          const field = document.createElement('textarea');
          field.value = link;
          field.setAttribute('readonly', '');
          field.style.position = 'fixed';
          field.style.left = '-9999px';
          document.body.appendChild(field);
          field.select();
          const ok = document.execCommand('copy');
          field.remove();
          if (!ok) throw new Error('Clipboard is not available in this browser.');
          return link;
        });
      }
      return Promise.reject(new Error('Clipboard is not available in this browser.'));
    }
  };
  ready.then((mode) => { share.mode = mode; });
  window.NeurobuddyShare = share;
})();
