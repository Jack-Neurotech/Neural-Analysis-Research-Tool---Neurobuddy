/* Browser-native Neurobuddy API. Replaces FastAPI HTTP when no local server is running.
   Library mutations persist in IndexedDB/OPFS. Analysis runs in the Pyodide worker. */
(() => {
  'use strict';
  const origFetch = window.fetch.bind(window);
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const TASKS = ['oddball', 'motor', 'sleep', 'unspecified'];
  const TYPES = ['baseline', 'testing'];
  const SIGNALS = ['.set', '.edf', '.bdf', '.vhdr', '.fif', '.fif.gz'];
  const COMPANIONS = ['.fdt', '.eeg', '.vmrk'];
  const EVENTS = ['.tsv', '.csv', '.json', '.txt'];
  const MAX_FILES = 24;
  const MAX_FILE_BYTES = 400 * 1024 * 1024;
  const OPENNEURO = 'https://openneuro.org/crn/graphql';
  const ACCESSION = /^(?:https?:\/\/openneuro\.org\/datasets\/)?(ds\d{6,8})(?:\/.*)?$/i;

  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'private, no-store' }
  });
  const fail = (status, detail) => json({ detail }, status);
  const isSignal = (n) => SIGNALS.some((ext) => String(n || '').toLowerCase().endsWith(ext));
  const baseName = (n) => {
    const s = String(n || '');
    const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
    return i >= 0 ? s.slice(i + 1) : s;
  };
  const emit = (message, extra) => {
    try {
      window.dispatchEvent(new CustomEvent('neurobuddy:progress', { detail: Object.assign({ message }, extra || {}) }));
    } catch { /* ignore */ }
  };

  const runtime = {
    status: 'idle',
    ready: false,
    versions: null,
    error: null,
    worker: null,
    pending: new Map(),
    queue: Promise.resolve(),
    generation: 0
  };

  function workerUrl() {
    return new URL('v2/pyodide-worker.js', document.baseURI || location.href).href;
  }

  function spawnWorker() {
    if (runtime.worker) {
      try { runtime.worker.terminate(); } catch { /* ignore */ }
    }
    runtime.generation += 1;
    runtime.ready = false;
    runtime.status = 'loading';
    const worker = new Worker(workerUrl());
    runtime.worker = worker;
    worker.onmessage = (event) => {
      const msg = event.data || {};
      if (msg.type === 'progress') {
        emit(msg.message, msg);
        return;
      }
      if (msg.type === 'ready') {
        runtime.ready = true;
        runtime.status = 'ready';
        runtime.versions = msg.versions;
        runtime.error = null;
        emit('Browser Python runtime ready.', { phase: 'ready' });
        return;
      }
      const waiter = runtime.pending.get(msg.id);
      if (!waiter) return;
      runtime.pending.delete(msg.id);
      if (msg.type === 'result') waiter.resolve(msg);
      else waiter.reject(new Error(msg.error || 'Analysis worker failed.'));
    };
    worker.onerror = (event) => {
      runtime.status = 'error';
      runtime.error = event.message || 'Pyodide worker crashed.';
      emit(runtime.error, { phase: 'error' });
      for (const [id, waiter] of runtime.pending) {
        waiter.reject(new Error(runtime.error));
        runtime.pending.delete(id);
      }
    };
    worker.postMessage({ type: 'init' });
    return worker;
  }

  function ensureWorker() {
    if (!runtime.worker || runtime.status === 'error') spawnWorker();
    return runtime.worker;
  }

  function runJob(payload, buffers) {
    ensureWorker();
    return new Promise((resolve, reject) => {
      runtime.pending.set(payload.id, { resolve, reject });
      runtime.worker.postMessage(payload, buffers || []);
    });
  }

  function enqueue(task) {
    runtime.queue = runtime.queue.then(task, task);
    return runtime.queue;
  }

  function recoverWorker() {
    spawnWorker();
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
              source: r.source || null,
              files, ready, task: { task: r.task_type, status: ready ? 'ready' : 'empty', warnings: [] }
            };
          })
        }))
      })),
      pipeline_version: (runtime.versions && runtime.versions.neurobuddy) || '0.7.1-optimized'
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

  function createShelves(db, athleteId, task) {
    for (const classification of ['baseline', 'baseline', 'baseline', 'testing']) {
      db.recordings.push({
        id: store().uid(), athlete_id: athleteId, classification, source_name: '', directory: store().uid(),
        created_at: store().now(), task_type: task, origin: 'downloads'
      });
    }
  }

  async function readJson(init) {
    if (!init || !init.body) return {};
    if (typeof init.body === 'string') return JSON.parse(init.body || '{}');
    if (init.body instanceof Blob) return JSON.parse(await init.body.text() || '{}');
    return {};
  }

  async function fileUploads(init) {
    const body = init && init.body;
    if (body && typeof FormData !== 'undefined' && body instanceof FormData) {
      const files = [];
      for (const [, value] of body.entries()) {
        if (value && typeof value === 'object' && typeof value.arrayBuffer === 'function' && value.name) {
          const buffer = await value.arrayBuffer();
          files.push({ name: baseName(value.name), size: value.size || buffer.byteLength, buffer });
        }
      }
      return { slot: body.get('slot') || 'signal', files };
    }
    return { slot: 'signal', files: [] };
  }

  const S = () => window.NeurobuddyStore;
  let storeReady = null;
  function store() {
    if (!storeReady) {
      const api = S();
      if (!api) throw new Error('NeurobuddyStore failed to load.');
      storeReady = api;
      api.persistPermission();
    }
    return storeReady;
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
    return { bases, test, needed };
  }

  async function filesForRecording(db, recordingId) {
    const rows = db.files.filter((f) => f.recording_id === recordingId);
    const out = [];
    for (const row of rows) {
      const buffer = await store().readBlob('recordings', recordingId, row.name, row.storage);
      out.push({ path: row.name, name: row.name, buffer });
    }
    return out;
  }

  async function storeArtifacts(jobId, artifacts) {
    for (const item of artifacts || []) {
      await store().putArtifact(jobId, item.path, item.buffer, store().mimeOf(item.path));
      const key = jobId + '/' + item.path;
      if (blobUrls.has(key)) URL.revokeObjectURL(blobUrls.get(key));
      blobUrls.set(key, URL.createObjectURL(new Blob([item.buffer], { type: store().mimeOf(item.path) })));
    }
  }

  async function hydrateArtifacts(jobId) {
    const keys = await store().artifactKeys(jobId);
    for (const path of keys) {
      const key = jobId + '/' + path;
      if (blobUrls.has(key)) continue;
      const stored = await store().getArtifact(jobId, path);
      if (!stored) continue;
      blobUrls.set(key, URL.createObjectURL(new Blob([stored.buffer], { type: stored.mime || store().mimeOf(path) })));
    }
  }

  async function processSingle(db, rec, options) {
    const files = await filesForRecording(db, rec.id);
    if (!files.some((f) => isSignal(f.name))) throw Object.assign(new Error('Upload an EEG signal to this shelf first.'), { status: 422 });
    const id = store().uid();
    const msg = await runJob({
      type: 'analyze', id, kind: 'single',
      files, options: {
        artifact_mode: options.artifact_mode || 'legacy',
        mains_frequency_hz: options.mains_frequency_hz || 60,
        task_selected: rec.task_type || 'unspecified'
      }
    }, files.map((f) => f.buffer));
    return msg;
  }

  async function processAthlete(db, athlete, task, testId, options) {
    const { bases, test, needed } = chooseComparison(db, athlete.id, task, testId);
    const baselines = [];
    for (const rec of bases) {
      baselines.push({ id: rec.id, files: await filesForRecording(db, rec.id) });
    }
    const testFiles = await filesForRecording(db, test.id);
    const id = store().uid();
    const transfer = [];
    for (const rec of baselines) for (const f of rec.files) transfer.push(f.buffer);
    for (const f of testFiles) transfer.push(f.buffer);
    const msg = await runJob({
      type: 'analyze', id, kind: 'athlete',
      baselines, test: { id: test.id, files: testFiles },
      team_id: athlete.team_id, athlete_id: athlete.id,
      options: {
        artifact_mode: options.artifact_mode || 'legacy',
        mains_frequency_hz: options.mains_frequency_hz || 60,
        min_baselines: needed
      }
    }, transfer);
    msg.result.task_type = test.task_type;
    return msg;
  }

  async function executeQueuedJob(jobId) {
    const db = await store().loadWorkspace();
    const job = find(db, 'jobs', jobId);
    if (!job) return;
    job.status = 'running';
    job.updated_at = store().now();
    await store().saveWorkspace(db);
    emit('Analysis running…', { phase: 'analyze', jobId });
    try {
      const options = job.options || {};
      let msg;
      if (job.mode === 'single') {
        const rec = must(db, 'recordings', job.target_id, 'Recording');
        msg = await processSingle(db, rec, options);
        msg.result.recording_id = rec.id;
      } else if (job.mode === 'athlete') {
        const athlete = must(db, 'athletes', job.target_id, 'Athlete');
        msg = await processAthlete(db, athlete, options.task_type, job.test_recording_id, options);
      } else {
        const team = must(db, 'teams', job.target_id, 'Team');
        const members = [];
        const artifacts = [];
        for (const athlete of db.athletes.filter((a) => a.team_id === team.id)) {
          try {
            const one = await processAthlete(db, athlete, options.task_type, null, options);
            const prefix = 'athletes/' + athlete.id + '/';
            for (const item of one.artifacts || []) {
              artifacts.push({ path: prefix + item.path, buffer: item.buffer });
            }
            if (one.result && one.result.entrypoint) {
              one.result.relative_report = prefix + one.result.entrypoint;
            }
            members.push({
              athlete_id: athlete.id, athlete_name: athlete.name, status: 'completed',
              relative_report: prefix + 'athlete_report.html', result: one.result
            });
          } catch (err) {
            members.push({ athlete_id: athlete.id, athlete_name: athlete.name, status: 'skipped', message: err.message });
          }
        }
        if (!members.some((row) => row.status === 'completed')) {
          throw Object.assign(new Error('No athletes have enough compatible uploaded baseline EEGs and 1 testing EEG for this task. Oddball needs 2 baselines; sleep, motor, and unspecified need 3.'), { status: 422 });
        }
        msg = {
          result: { mode: 'team', team_id: team.id, members, task_type: options.task_type, entrypoint: null },
          artifacts
        };
      }
      await storeArtifacts(jobId, msg.artifacts);
      const latest = await store().loadWorkspace();
      const row = find(latest, 'jobs', jobId);
      if (!row) return;
      row.status = 'completed';
      row.error = null;
      row.result = msg.result;
      row.updated_at = store().now();
      await store().saveWorkspace(latest);
      emit('Analysis complete.', { phase: 'done', jobId });
    } catch (err) {
      const latest = await store().loadWorkspace();
      const row = find(latest, 'jobs', jobId);
      if (row) {
        row.status = 'failed';
        row.error = (err && err.message) ? String(err.message).slice(0, 1600) : 'Analysis failed';
        row.updated_at = store().now();
        await store().saveWorkspace(latest);
      }
      emit(row && row.error || 'Analysis failed', { phase: 'error', jobId });
    }
  }

  const blobUrls = new Map();
  async function artifactResponse(jobId, pathName) {
    const stored = await store().getArtifact(jobId, pathName);
    if (!stored) {
      const db = await store().loadWorkspace();
      const job = find(db, 'jobs', jobId);
      if (!job) return fail(404, 'Job not found');
      if (pathName.endsWith('.json')) {
        return new Response(JSON.stringify(job.result || {}, null, 2), {
          status: 200, headers: { 'content-type': 'application/json', 'cache-control': 'private, no-store' }
        });
      }
      return fail(404, 'Report file not found');
    }
    const mime = stored.mime || store().mimeOf(pathName);
    return new Response(stored.buffer, { status: 200, headers: { 'content-type': mime, 'cache-control': 'private, no-store' } });
  }

  async function artifactObjectUrl(id, path) {
    const key = id + '/' + path;
    if (blobUrls.has(key)) return blobUrls.get(key);
    const stored = await store().getArtifact(id, path);
    if (!stored) return `/api/v2/artifacts/${encodeURIComponent(id)}/${path}`;
    const url = URL.createObjectURL(new Blob([stored.buffer], { type: stored.mime || 'text/html' }));
    blobUrls.set(key, url);
    return url;
  }

  async function healthBody() {
    const info = await store().storageInfo();
    return {
      ok: true,
      engine: 'Neurobuddy v0.7.1',
      pipeline_version: (runtime.versions && runtime.versions.neurobuddy) || '0.7.1-optimized',
      mode: 'browser-native',
      ai_connected: false,
      repository_connected: true,
      sample_data: false,
      pyodide_ready: runtime.ready,
      pyodide_status: runtime.status,
      pyodide_error: runtime.error,
      versions: runtime.versions,
      storage: info
    };
  }

  const importJobs = new Map();

  function parseDatasetId(value) {
    const match = String(value || '').trim().match(ACCESSION);
    if (!match) throw Object.assign(new Error('Enter a valid OpenNeuro accession such as ds003061.'), { status: 422 });
    return match[1].toLowerCase();
  }
  function validateTag(tag) {
    if (!/^[0-9A-Za-z._-]{1,80}$/.test(tag || '')) {
      throw Object.assign(new Error('Invalid snapshot version.'), { status: 422 });
    }
    return tag;
  }
  function validateUrl(url, datasetId) {
    let parts;
    try { parts = new URL(url); } catch {
      throw Object.assign(new Error('OpenNeuro did not provide a usable download URL.'), { status: 422 });
    }
    if (parts.protocol !== 'https:' || parts.username || parts.password) {
      throw Object.assign(new Error('Refusing a download URL that is not HTTPS on the trusted OpenNeuro host.'), { status: 422 });
    }
    const host = (parts.hostname || '').toLowerCase();
    const path = parts.pathname || '';
    const allowed = (
      (host === 's3.amazonaws.com' && path.startsWith('/openneuro.org/' + datasetId + '/')) ||
      (host === 'openneuro.org.s3.amazonaws.com' && path.startsWith('/' + datasetId + '/')) ||
      (host === 'openneuro.org' && path.startsWith('/crn/datasets/' + datasetId + '/'))
    );
    if (!allowed) throw Object.assign(new Error('Refusing a download URL outside this OpenNeuro dataset.'), { status: 422 });
    return url;
  }

  async function graphql(query, variables) {
    let response;
    try {
      response = await origFetch(OPENNEURO, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ query, variables: variables || {} })
      });
    } catch (err) {
      throw Object.assign(new Error('Cannot reach OpenNeuro right now. Verify your network connection. ' + (err.message || '')), { status: 502 });
    }
    if (!response.ok) throw Object.assign(new Error('Cannot reach OpenNeuro right now.'), { status: 502 });
    const payload = await response.json();
    if (payload.errors && payload.errors.length) {
      const message = payload.errors[0].message || 'GraphQL error';
      const lowered = String(message).toLowerCase();
      if (['does not exist', 'not found', 'no snapshot', 'unknown dataset'].some((t) => lowered.includes(t))) {
        throw Object.assign(new Error('Dataset unavailable or not public.'), { status: 404 });
      }
      throw Object.assign(new Error('OpenNeuro returned a GraphQL error; check the dataset accession, snapshot, and API status.'), { status: 502 });
    }
    return payload.data || {};
  }

  async function downloadOpenNeuro(datasetId, urls, onProgress) {
    const url = validateUrl((urls || []).find((u) => typeof u === 'string') || '', datasetId);
    let response;
    try {
      response = await origFetch(url, { cache: 'no-store' });
    } catch (err) {
      throw Object.assign(new Error('Browser blocked the OpenNeuro download (CORS or network). Save the file locally and use Downloads import.'), { status: 502 });
    }
    if (!response.ok) throw Object.assign(new Error('OpenNeuro download failed (' + response.status + ').'), { status: 502 });
    if (!response.body || !response.body.getReader) {
      const buffer = await response.arrayBuffer();
      if (onProgress) onProgress(buffer.byteLength, buffer.byteLength);
      return buffer;
    }
    const total = Number(response.headers.get('content-length')) || 0;
    const reader = response.body.getReader();
    const chunks = [];
    let received = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.byteLength;
      if (onProgress) onProgress(received, total);
    }
    const out = new Uint8Array(received);
    let offset = 0;
    for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.byteLength; }
    return out.buffer;
  }

  async function fileAtPath(datasetId, tag, path) {
    const parts = String(path || '').split('/').filter(Boolean);
    let tree = null;
    let entries = [];
    for (let i = 0; i <= parts.length; i++) {
      const data = await graphql(
        'query($id:ID!,$tag:String!,$tree:String){snapshot(datasetId:$id,tag:$tag){files(tree:$tree){id filename size directory annexed urls}}}',
        { id: datasetId, tag, tree }
      );
      if (!data.snapshot) throw Object.assign(new Error('Public snapshot not available.'), { status: 404 });
      entries = data.snapshot.files || [];
      if (i === parts.length) break;
      const match = entries.find((item) => item.filename === parts[i]);
      if (!match) throw Object.assign(new Error('Snapshot path not found: ' + path), { status: 404 });
      if (i === parts.length - 1 && !match.directory) {
        match.path = path;
        return match;
      }
      if (!match.directory) throw Object.assign(new Error('Snapshot path not found: ' + path), { status: 404 });
      tree = match.id;
    }
    throw Object.assign(new Error('Select an EEG file, not a folder.'), { status: 422 });
  }

  function bidsEntities(filename) {
    const out = {};
    for (const key of ['sub', 'ses', 'task', 'acq', 'run', 'rec', 'space', 'desc']) {
      const match = String(filename).match(new RegExp('(?:^|_)' + key + '-([A-Za-z0-9]+)(?:_|\\.|$)'));
      if (match) out[key] = match[1];
    }
    return out;
  }
  function entitiesCompatible(sidecar, signal) {
    const a = bidsEntities(sidecar), b = bidsEntities(signal);
    for (const key of Object.keys(a)) {
      if (b[key] && a[key].toLowerCase() !== b[key].toLowerCase()) return false;
    }
    return true;
  }
  function motorFilename(name) {
    const task = (bidsEntities(name).task || '').toLowerCase();
    return ['motion', 'motor', 'imagery', 'eegmmidb', 'motorimagery', 'motorloc', 'execution'].includes(task) ||
      task.includes('motor') || task.includes('imagery');
  }
  function motorSubtype(text) {
    const sample = String(text || '').replace(/^\uFEFF/, '');
    const first = sample.split(/\r?\n/, 1)[0] || '';
    const delim = first.includes('\t') ? '\t' : ',';
    const rows = sample.split(/\r?\n/).filter((line) => line.length);
    if (rows.length < 2) return null;
    const header = rows[0].split(delim).map((c) => c.trim().toLowerCase());
    const indexes = header.map((n, i) => ['value', 'trial_type', 'trialtype'].includes(n) ? i : -1).filter((i) => i >= 0);
    if (!indexes.length) return null;
    const kinds = new Set();
    const taskRe = /^TASK([1-4])T([0-2])$/i;
    for (const line of rows.slice(1)) {
      const cells = line.split(delim);
      for (const index of indexes) {
        const raw = (cells[index] || '').trim();
        if (!raw) continue;
        const match = raw.match(taskRe);
        if (match) {
          const taskId = Number(match[1]); const code = Number(match[2]);
          if (code === 0) continue;
          if (taskId === 2 || taskId === 4) kinds.add('imagery');
          else if (taskId === 1 || taskId === 3) kinds.add('execution');
          continue;
        }
        const token = raw.toLowerCase().replace(/[-\s]/g, '_');
        if (['imagery', 'motor_imagery', 'imagine', 'imagined'].includes(token) || token.endsWith('_imagery')) kinds.add('imagery');
        if (['execution', 'motor_execution', 'executed'].includes(token) || token.endsWith('_execution')) kinds.add('execution');
      }
    }
    if (kinds.size === 1 && kinds.has('imagery')) return 'imagery';
    if (kinds.size === 1 && kinds.has('execution')) return 'execution';
    return null;
  }

  async function saveBytesToShelf(db, shelfId, filename, buffer, origin, source) {
    const shelf = must(db, 'recordings', shelfId, 'Recording');
    const name = baseName(filename);
    if (db.files.some((f) => f.recording_id === shelfId && f.name.toLowerCase() === name.toLowerCase())) {
      throw Object.assign(new Error('That file already exists in this EEG shelf. Remove it first to replace.'), { status: 409 });
    }
    const written = await store().writeBlob('recordings', shelfId, name, buffer);
    db.files.push({ id: store().uid(), recording_id: shelfId, name, size_bytes: written.size, storage: written.storage });
    const all = db.files.filter((f) => f.recording_id === shelfId).map((f) => f.name);
    shelf.source_name = all.find(isSignal) || shelf.source_name;
    if (origin) shelf.origin = origin;
    if (source) shelf.source = source;
    await store().saveWorkspace(db);
    return shelf;
  }

  async function backupZip() {
    const db = await store().loadWorkspace();
    const files = [{ name: 'workspace.json', data: store().encodeUtf8(JSON.stringify(db)) }];
    for (const row of db.files) {
      try {
        const buffer = await store().readBlob('recordings', row.recording_id, row.name, row.storage);
        files.push({ name: 'recordings/' + row.recording_id + '/' + row.name, data: new Uint8Array(buffer) });
      } catch { /* skip missing */ }
    }
    for (const job of db.jobs) {
      if (!job.result) continue;
      files.push({
        name: 'jobs/' + job.id + '/result.json',
        data: store().encodeUtf8(JSON.stringify(job.result))
      });
    }
    return store().zipStore(files);
  }

  async function restoreZip(buffer) {
    const files = store().unzipStore(buffer);
    const meta = files.find((f) => f.name === 'workspace.json');
    if (!meta) throw Object.assign(new Error('Backup is missing workspace.json.'), { status: 422 });
    const db = JSON.parse(new TextDecoder().decode(meta.data));
    if (!db || !Array.isArray(db.teams) || !Array.isArray(db.jobs)) {
      throw Object.assign(new Error('Backup workspace is not a Neurobuddy archive.'), { status: 422 });
    }
    for (const row of db.files || []) {
      const entry = files.find((f) => f.name === 'recordings/' + row.recording_id + '/' + row.name);
      if (!entry) continue;
      const written = await store().writeBlob('recordings', row.recording_id, row.name, entry.data);
      row.storage = written.storage;
      row.size_bytes = written.size;
    }
    await store().saveWorkspace(db);
    return { restored: true, teams: db.teams.length, athletes: db.athletes.length, recordings: db.recordings.length };
  }

  async function handle(url, init) {
    const method = (init && init.method || 'GET').toUpperCase();
    const parsed = new URL(url, location.origin);
    const path = parsed.pathname.replace(/^\/api/, '');
    const db = await store().loadWorkspace();
    try {
      if (method === 'GET' && path === '/v2/health') return json(await healthBody());
      if (method === 'GET' && path === '/v2/shelf-library') return json(library(db));
      if (method === 'GET' && path === '/v2/jobs') {
        for (const job of db.jobs.filter((row) => row.status === 'completed')) await hydrateArtifacts(job.id);
        return json({ jobs: db.jobs.map((j) => jobPublic(j, false)) });
      }
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
      if (method === 'GET' && path === '/v2/backup') {
        const zip = await backupZip();
        return new Response(zip, {
          status: 200,
          headers: {
            'content-type': 'application/zip',
            'content-disposition': 'attachment; filename="neurobuddy-backup.zip"',
            'cache-control': 'private, no-store'
          }
        });
      }
      if (method === 'POST' && path === '/v2/restore') {
        const body = init && init.body;
        let buffer;
        if (body instanceof FormData) {
          const file = body.get('backup') || body.get('file');
          if (!file || typeof file.arrayBuffer !== 'function') return fail(422, 'Choose a Neurobuddy backup ZIP.');
          buffer = await file.arrayBuffer();
        } else if (body instanceof Blob) buffer = await body.arrayBuffer();
        else return fail(422, 'Choose a Neurobuddy backup ZIP.');
        return json(await restoreZip(buffer), 201);
      }

      let m = path.match(/^\/v2\/jobs\/([^/]+)$/);
      if (m && method === 'GET') {
        if (!UUID.test(m[1])) return fail(422, 'Unknown analysis report.');
        await hydrateArtifacts(m[1]);
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
            job.updated_at = store().now();
            await store().saveWorkspace(db);
            return json({ deleted: true, id: job.id, athlete_id: athleteId, removed: 'athlete' });
          }
        }
        db.jobs = db.jobs.filter((row) => row.id !== job.id);
        await store().deleteArtifacts(job.id);
        await store().saveWorkspace(db);
        return json({ deleted: true, id: job.id, removed: 'job' });
      }

      m = path.match(/^\/v2\/jobs\/([^/]+)\/retry$/);
      if (m && method === 'POST') {
        const job = must(db, 'jobs', m[1], 'Job');
        if (!['failed', 'interrupted'].includes(job.status)) return fail(409, 'Only failed or interrupted jobs can be retried.');
        recoverWorker();
        return handle(new URL('/api/v2/shelf-jobs', location.origin).href, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            mode: job.mode, target_id: job.target_id, test_recording_id: job.test_recording_id,
            task_type: (job.options && job.options.task_type) || null,
            artifact_mode: (job.options && job.options.artifact_mode) || 'legacy',
            mains_frequency_hz: (job.options && job.options.mains_frequency_hz) || 60
          })
        });
      }

      if (method === 'POST' && path === '/v2/shelf-teams') {
        const body = await readJson(init);
        const name = String(body.name || '').trim();
        if (!name) return fail(422, 'Team name is required.');
        const row = { id: store().uid(), name, created_at: store().now() };
        db.teams.push(row);
        await store().saveWorkspace(db);
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
        const row = { id: store().uid(), team_id: m[1], name, created_at: store().now() };
        db.athletes.push(row);
        createShelves(db, row.id, task);
        await store().saveWorkspace(db);
        return json({ id: row.id, team_id: m[1], name, created_shelves: 4 }, 201);
      }

      m = path.match(/^\/v2\/shelf-teams\/([^/]+)$/);
      if (m && method === 'DELETE') {
        must(db, 'teams', m[1], 'Team');
        const aids = db.athletes.filter((a) => a.team_id === m[1]).map((a) => a.id);
        const rids = db.recordings.filter((r) => aids.includes(r.athlete_id)).map((r) => r.id);
        for (const rid of rids) await store().deletePrefix('recordings', rid);
        db.files = db.files.filter((f) => !rids.includes(f.recording_id));
        db.recordings = db.recordings.filter((r) => !aids.includes(r.athlete_id));
        db.athletes = db.athletes.filter((a) => a.team_id !== m[1]);
        db.teams = db.teams.filter((t) => t.id !== m[1]);
        await store().saveWorkspace(db);
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
          id: store().uid(), athlete_id: m[1], classification: kind, source_name: '', directory: store().uid(),
          created_at: store().now(), task_type: task, origin: 'downloads'
        };
        db.recordings.push(row);
        await store().saveWorkspace(db);
        return json({ id: row.id, task_type: task, classification: kind }, 201);
      }

      m = path.match(/^\/v2\/shelf-athletes\/([^/]+)$/);
      if (m && method === 'DELETE') {
        must(db, 'athletes', m[1], 'Athlete');
        const rids = db.recordings.filter((r) => r.athlete_id === m[1]).map((r) => r.id);
        for (const rid of rids) await store().deletePrefix('recordings', rid);
        db.files = db.files.filter((f) => !rids.includes(f.recording_id));
        db.recordings = db.recordings.filter((r) => r.athlete_id !== m[1]);
        db.athletes = db.athletes.filter((a) => a.id !== m[1]);
        await store().saveWorkspace(db);
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
        await store().saveWorkspace(db);
        return json(changes);
      }
      if (m && method === 'DELETE') {
        must(db, 'recordings', m[1], 'Recording');
        await store().deletePrefix('recordings', m[1]);
        db.files = db.files.filter((f) => f.recording_id !== m[1]);
        db.recordings = db.recordings.filter((r) => r.id !== m[1]);
        await store().saveWorkspace(db);
        return json({ deleted: true, id: m[1] });
      }

      m = path.match(/^\/v2\/shelves\/([^/]+)\/files\/([^/]+)$/);
      if (m && method === 'DELETE') {
        const shelf = must(db, 'recordings', m[1], 'Recording');
        const file = db.files.find((f) => f.id === m[2] && f.recording_id === m[1]);
        if (!file) return fail(404, 'File not in EEG shelf.');
        await store().deleteBlob('recordings', shelf.id, file.name, file.storage);
        db.files = db.files.filter((f) => f.id !== file.id);
        const remains = db.files.filter((f) => f.recording_id === shelf.id).map((f) => f.name);
        shelf.source_name = remains.find(isSignal) || '';
        await store().saveWorkspace(db);
        return json({ deleted: true });
      }

      m = path.match(/^\/v2\/shelves\/([^/]+)\/files$/);
      if (m && method === 'POST') {
        const shelf = must(db, 'recordings', m[1], 'Recording');
        const { slot, files } = await fileUploads(init);
        if (!['signal', 'companion', 'events'].includes(slot)) return fail(422, 'Select signal, companion, or events.');
        if (!files.length) return fail(422, 'Select 1–24 files.');
        if (files.length > MAX_FILES) return fail(422, 'Select 1–24 files.');
        const existing = db.files.filter((f) => f.recording_id === shelf.id).map((f) => f.name);
        const names = files.map((f) => f.name);
        if (new Set(names.map((n) => n.toLowerCase())).size !== names.length) return fail(422, 'Duplicate file names in upload.');
        if (existing.some((n) => names.some((x) => x.toLowerCase() === n.toLowerCase()))) {
          return fail(409, 'That file already exists in this EEG shelf. Remove it first to replace.');
        }
        if (existing.length + names.length > MAX_FILES) return fail(422, 'Too many files in EEG shelf.');
        if (existing.filter(isSignal).length + names.filter(isSignal).length > 1) {
          return fail(422, 'Each EEG shelf holds one signal recording. Add a second shelf for another EEG.');
        }
        if (slot === 'signal' && names.some((n) => !isSignal(n))) {
          return fail(422, 'The signal slot accepts .set, .edf, .bdf, .vhdr, .fif or .fif.gz only.');
        }
        if (slot === 'companion' && names.some((n) => !COMPANIONS.some((ext) => n.toLowerCase().endsWith(ext)))) {
          return fail(422, 'Companion slot accepts .fdt, .eeg or .vmrk.');
        }
        if (slot === 'events' && names.some((n) => !EVENTS.some((ext) => n.toLowerCase().endsWith(ext)))) {
          return fail(422, 'Annotation slot accepts .tsv, .csv, .json or .txt.');
        }
        for (const file of files) {
          if (!file.size) return fail(422, 'Empty file: ' + file.name);
          if (file.size > MAX_FILE_BYTES) return fail(413, 'File too large.');
          const written = await store().writeBlob('recordings', shelf.id, file.name, file.buffer);
          db.files.push({
            id: store().uid(), recording_id: shelf.id, name: file.name,
            size_bytes: written.size, storage: written.storage
          });
        }
        const all = db.files.filter((f) => f.recording_id === shelf.id).map((f) => f.name);
        shelf.source_name = all.find(isSignal) || shelf.source_name;
        await store().saveWorkspace(db);
        return json({ id: shelf.id, uploaded: names, file_count: all.length }, 201);
      }

      if (method === 'POST' && path === '/v2/shelf-jobs') {
        const req = await readJson(init);
        if (!['single', 'athlete', 'team'].includes(req.mode)) return fail(422, 'Select Single EEG, Test Athlete, or Test Team.');
        if (req.artifact_mode && !['legacy', 'experimental'].includes(req.artifact_mode)) return fail(422, 'Unsupported EEG processing settings.');
        if (req.mains_frequency_hz && ![50, 60].includes(Number(req.mains_frequency_hz))) return fail(422, 'Unsupported EEG processing settings.');
        if (req.task_type && !TASKS.includes(req.task_type)) return fail(422, 'Test Type must be Oddball, Motor-imagery, Sleep, or Unspecified.');
        let athleteId = null, teamId = null;
        if (req.mode === 'single') {
          const rec = must(db, 'recordings', req.target_id, 'Recording');
          if (!rec.source_name) return fail(422, 'Upload an EEG signal to this shelf first.');
          const athlete = must(db, 'athletes', rec.athlete_id, 'Athlete');
          athleteId = athlete.id; teamId = athlete.team_id;
        } else if (req.mode === 'athlete') {
          const athlete = must(db, 'athletes', req.target_id, 'Athlete');
          athleteId = athlete.id; teamId = athlete.team_id;
          try { chooseComparison(db, athlete.id, req.task_type, req.test_recording_id); }
          catch (err) { return fail(err.status || 422, err.message); }
        } else {
          must(db, 'teams', req.target_id, 'Team');
          teamId = req.target_id;
        }
        ensureWorker();
        const job = {
          id: store().uid(), mode: req.mode, target_id: req.target_id, test_recording_id: req.test_recording_id || null,
          created_at: store().now(), updated_at: store().now(), status: 'queued', error: null, result: null,
          result_dir: store().uid(), team_id: teamId, athlete_id: athleteId,
          options: {
            task_type: req.task_type || null,
            artifact_mode: req.artifact_mode || 'legacy',
            mains_frequency_hz: req.mains_frequency_hz || 60
          }
        };
        db.jobs.unshift(job);
        await store().saveWorkspace(db);
        enqueue(() => executeQueuedJob(job.id));
        return json({ id: job.id, status: 'queued', mode: req.mode }, 202);
      }

      m = path.match(/^\/v2\/artifacts\/([^/]+)\/(.+)$/);
      if (m && method === 'GET') {
        must(db, 'jobs', m[1], 'Job');
        return artifactResponse(m[1], decodeURIComponent(m[2]));
      }

      m = path.match(/^\/v2\/openneuro\/([^/]+)$/);
      if (m && method === 'GET') {
        const ds = parseDatasetId(m[1]);
        const data = await graphql('query($id:ID!){dataset(id:$id){id name latestSnapshot{tag description{Name DatasetDOI}} snapshots{tag}}}', { id: ds });
        const found = data.dataset;
        if (!found) return fail(404, 'Dataset unavailable or not public.');
        const snap = found.latestSnapshot || {};
        const tag = snap.tag;
        if (!tag) return fail(404, 'Dataset has no public snapshot.');
        const description = snap.description || {};
        const tags = (found.snapshots || []).map((item) => item.tag).filter(Boolean);
        return json({
          id: found.id || ds, name: found.name || ds, tag,
          description: description.Name || '', doi: description.DatasetDOI || '',
          tags: tags.length ? tags : [tag]
        });
      }
      m = path.match(/^\/v2\/openneuro\/([^/]+)\/tree$/);
      if (m && method === 'GET') {
        const ds = parseDatasetId(m[1]);
        const tag = validateTag(parsed.searchParams.get('tag') || '');
        const tree = parsed.searchParams.get('tree');
        if (tree && !/^[a-f0-9]{40,64}$/.test(tree)) return fail(422, 'Invalid tree ID.');
        const data = await graphql(
          'query($id:ID!,$tag:String!,$tree:String){snapshot(datasetId:$id,tag:$tag){files(tree:$tree){id filename size directory annexed urls}}}',
          { id: ds, tag, tree }
        );
        if (!data.snapshot) return fail(404, 'Public snapshot not available.');
        const items = data.snapshot.files || [];
        if (items.length > 3000) return fail(413, 'Folder too large to display at once.');
        return json({ dataset_id: ds, tag, tree, files: items });
      }
      m = path.match(/^\/v2\/openneuro\/([^/]+)\/file$/);
      if (m && method === 'GET') {
        const ds = parseDatasetId(m[1]);
        const tag = validateTag(parsed.searchParams.get('tag') || '');
        const filePath = parsed.searchParams.get('path') || '';
        const record = await fileAtPath(ds, tag, filePath);
        const lower = (record.filename || '').toLowerCase();
        const previewable = ['readme', 'changes', 'license', 'citation'].includes(lower) ||
          ['.tsv', '.csv', '.txt', '.json', '.vhdr', '.vmrk', '.md'].some((ext) => lower.endsWith(ext));
        if (!previewable) return fail(422, 'This file is not opened as text.');
        const buffer = await downloadOpenNeuro(ds, record.urls);
        const text = new TextDecoder('utf-8', { fatal: false }).decode(buffer.slice(0, 1_500_000));
        const clipped = text.length > 48000;
        return json({
          dataset_id: ds, snapshot: tag, path: filePath, filename: record.filename,
          size: record.size, truncated: clipped, text: clipped ? text.slice(0, 48000) : text
        });
      }
      m = path.match(/^\/v2\/openneuro\/([^/]+)\/motor-labels$/);
      if (m && method === 'GET') {
        const ds = parseDatasetId(m[1]);
        const tag = validateTag(parsed.searchParams.get('tag') || '');
        const folder = (parsed.searchParams.get('path') || '').replace(/^\/+|\/+$/g, '');
        const treeId = folder ? (await fileAtPath(ds, tag, folder).catch(() => null) || {}).id : null;
        const data = await graphql(
          'query($id:ID!,$tag:String!,$tree:String){snapshot(datasetId:$id,tag:$tag){files(tree:$tree){id filename size directory annexed urls}}}',
          { id: ds, tag, tree: folder ? treeId : null }
        );
        const entries = ((data.snapshot || {}).files || []).map((item) => ({
          ...item, path: folder ? folder + '/' + item.filename : item.filename
        }));
        const labels = [];
        if (entries.some((item) => motorFilename(item.filename || ''))) {
          for (const signal of entries) {
            const name = signal.filename || '';
            if (signal.directory || !name.toLowerCase().endsWith('.set') || !motorFilename(name)) continue;
            const events = entries.filter((item) => !item.directory && /_events\.(tsv|csv)$/i.test(item.filename || '') && entitiesCompatible(item.filename, name));
            if (events.length !== 1) continue;
            try {
              const buffer = await downloadOpenNeuro(ds, events[0].urls);
              const text = new TextDecoder().decode(buffer.slice(0, 1_500_000));
              const label = motorSubtype(text);
              if (label === 'imagery' || label === 'execution') {
                labels.push({ path: events[0].path, filename: events[0].filename, label, signal: signal.path });
              }
            } catch { /* skip unread events */ }
          }
        }
        return json({ dataset_id: ds, snapshot: tag, path: folder, labels });
      }
      m = path.match(/^\/v2\/openneuro\/([^/]+)\/sleep-correspondence$/);
      if (m && method === 'GET') {
        const ds = parseDatasetId(m[1]);
        const tag = validateTag(parsed.searchParams.get('tag') || '');
        const folder = (parsed.searchParams.get('path') || '').replace(/^\/+|\/+$/g, '');
        const data = await graphql(
          'query($id:ID!,$tag:String!,$tree:String){snapshot(datasetId:$id,tag:$tag){files(tree:$tree){id filename size directory annexed urls}}}',
          { id: ds, tag, tree: null }
        );
        const entries = ((data.snapshot || {}).files || []).map((item) => ({
          ...item, path: folder ? folder + '/' + item.filename : item.filename
        }));
        const labels = [];
        const seen = new Set();
        for (const signal of entries) {
          const name = signal.filename || '';
          if (signal.directory || !name.toLowerCase().endsWith('.set')) continue;
          for (const item of entries) {
            const fname = item.filename || '';
            if (item.directory || !/\.(tsv|csv)$/i.test(fname)) continue;
            const sleepish = /scoring|hypnogram|stages|_events\./i.test(fname);
            if (!sleepish || !entitiesCompatible(fname, name)) continue;
            if (seen.has(item.path)) continue;
            seen.add(item.path);
            labels.push({ path: item.path, filename: fname, label: 'Corresponding', signal: signal.path });
          }
        }
        return json({ dataset_id: ds, snapshot: tag, path: folder, labels });
      }

      if (method === 'POST' && (path === '/v2/openneuro/save-tsv' || path === '/v2/openneuro/save-fdt' || path === '/v2/openneuro/import-recording')) {
        const body = await readJson(init);
        const ds = parseDatasetId(body.dataset_id);
        const tag = validateTag(body.tag);
        const filePath = body.path;
        const record = await fileAtPath(ds, tag, filePath);
        const filename = record.filename || baseName(filePath);
        if (path.endsWith('save-fdt') && !filename.toLowerCase().endsWith('.fdt')) {
          return fail(422, 'This endpoint saves a .fdt companion only.');
        }
        if (path.endsWith('save-tsv') && !/\.(tsv|csv|txt|json)$/i.test(filename)) {
          return fail(422, 'This endpoint saves an annotation table only.');
        }
        if (path.endsWith('import-recording') && !isSignal(filename)) {
          return fail(422, 'Download saves only a supported EEG signal.');
        }
        const jobId = store().uid();
        const job = {
          id: jobId, status: 'running', shelf_id: body.shelf_id || null, athlete_id: body.athlete_id || null,
          created_at: store().now(), error: null,
          progress: { percent: 0, bytes_done: 0, bytes_total: record.size || 0, files: [{ filename, status: 'downloading', role: 'signal', bytes: 0, size: record.size || 0 }], validated: false, saved: false }
        };
        importJobs.set(jobId, job);
        (async () => {
          try {
            const buffer = await downloadOpenNeuro(ds, record.urls, (done, total) => {
              job.progress.bytes_done = done;
              job.progress.bytes_total = total || job.progress.bytes_total;
              job.progress.percent = total ? Math.min(99, Math.round(100 * done / total)) : null;
              job.progress.files[0].bytes = done;
            });
            let shelfId = body.shelf_id;
            const latest = await store().loadWorkspace();
            if (!shelfId && body.athlete_id) {
              const athlete = must(latest, 'athletes', body.athlete_id, 'Athlete');
              const row = {
                id: store().uid(), athlete_id: athlete.id, classification: body.classification || 'baseline',
                source_name: '', directory: store().uid(), created_at: store().now(),
                task_type: body.task_type || 'unspecified', origin: 'openneuro'
              };
              latest.recordings.push(row);
              shelfId = row.id;
            }
            if (!shelfId) throw Object.assign(new Error('Select an EEG shelf first.'), { status: 422 });
            await saveBytesToShelf(latest, shelfId, filename, buffer, 'openneuro', {
              provider: 'openneuro', dataset_id: ds, snapshot: tag, primary_path: filePath, imported_at: store().now()
            });
            job.shelf_id = shelfId;
            job.status = 'completed';
            job.progress.percent = 100;
            job.progress.validated = true;
            job.progress.saved = true;
            job.progress.files[0].status = 'done';
          } catch (err) {
            job.status = 'failed';
            job.error = err.message || 'Import failed';
          }
        })();
        return json({ id: jobId, status: 'queued' }, 202);
      }

      m = path.match(/^\/v2\/import-jobs\/([^/]+)$/);
      if (m && method === 'GET') {
        const job = importJobs.get(m[1]);
        if (!job) return fail(404, 'Import job not found.');
        return json(job);
      }
      m = path.match(/^\/v2\/import-jobs\/([^/]+)\/cancel$/);
      if (m && method === 'POST') {
        const job = importJobs.get(m[1]);
        if (!job) return fail(404, 'Import job not found.');
        if (job.status === 'running' || job.status === 'queued') {
          job.status = 'cancelled';
          job.error = 'Import cancelled.';
        }
        return json(job);
      }
      m = path.match(/^\/v2\/import-jobs\/([^/]+)\/retry$/);
      if (m && method === 'POST') {
        return fail(409, 'Retry the download from the Connector.');
      }

      return fail(404, 'The EEG API endpoint ' + path + ' is not available in the browser runtime.');
    } catch (err) {
      return fail(err.status || 400, err.message || 'Request failed');
    }
  }

  const ready = origFetch('/api/v2/health', { cache: 'no-store' }).then(async (response) => {
    if (!response.ok) return 'browser';
    try {
      const payload = await response.clone().json();
      if (payload && payload.ok && payload.mode === 'local-only') return 'live';
    } catch { /* not JSON */ }
    return 'browser';
  }).catch(() => 'browser');

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
    artifactUrl(id, path) {
      const sync = blobUrls.get(id + '/' + path);
      if (sync) return sync;
      artifactObjectUrl(id, path);
      return `/api/v2/artifacts/${encodeURIComponent(id)}/${path}`;
    },
    copyLink() {
      const link = location.href.split('#')[0];
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
    },
    async backup() {
      const zip = await backupZip();
      const url = URL.createObjectURL(new Blob([zip], { type: 'application/zip' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'neurobuddy-backup.zip'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      return true;
    },
    async restore(file) {
      const buffer = await file.arrayBuffer();
      return restoreZip(buffer);
    },
    cancelAnalysis() {
      if (runtime.worker) {
        for (const [, waiter] of runtime.pending) waiter.reject(new Error('Analysis cancelled.'));
        runtime.pending.clear();
        recoverWorker();
      }
    }
  };
  ready.then((mode) => {
    share.mode = mode === 'live' ? 'live' : 'browser';
    if (mode !== 'live') ensureWorker();
  });
  window.NeurobuddyShare = share;
  window.NeurobuddyRuntime = runtime;
})();
