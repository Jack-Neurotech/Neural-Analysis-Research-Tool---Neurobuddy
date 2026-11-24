/* Neurobuddy Pyodide analysis worker. One runtime, many jobs. */
/* global loadPyodide, importScripts */
'use strict';

const PYODIDE_VERSION = '0.28.3';
const CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const LOAD_PACKAGES = ['numpy', 'scipy', 'matplotlib', 'pandas', 'h5py', 'micropip', 'packaging'];
const MICROPIP_PACKAGES = [
  'mne==1.8.0',
  'pymatreader==1.0.0',
  'jsonschema==4.23.0',
  'fastjsonschema==2.21.1',
  'lazy-loader==0.4',
  'pooch==1.8.2',
  'tqdm==4.67.1',
  'platformdirs==4.3.6',
  'decorator==5.1.1'
];

let pyodide = null;
let ready = false;
let currentJob = null;
let cancelFlag = false;

function post(msg) {
  self.postMessage(msg);
}
function progress(message, extra) {
  post(Object.assign({ type: 'progress', message: String(message || '') }, extra || {}));
}

function baseUrl() {
  const href = self.location.href;
  return href.slice(0, href.lastIndexOf('/') + 1);
}

async function fetchText(url) {
  const response = await fetch(url, { cache: 'force-cache' });
  if (!response.ok) throw new Error('Failed to load ' + url + ' (' + response.status + ')');
  return response.text();
}
async function fetchJson(url) {
  return JSON.parse(await fetchText(url));
}

async function resolveIndexURL() {
  const local = new URL('../vendor/pyodide/', self.location).href;
  try {
    const probe = await fetch(local + 'pyodide.js', { method: 'HEAD', cache: 'no-store' });
    if (probe.ok) return local;
  } catch { /* CDN */ }
  return CDN;
}

async function installPythonModules(runtime) {
  const root = new URL('../', self.location).href;
  const manifest = await fetchJson(root + 'pyodide/python-modules.json');
  const pkg = manifest.package || 'neurobuddy_v2';
  runtime.FS.mkdirTree('/pkg/' + pkg);
  for (const file of manifest.files) {
    const url = root + pkg + '/' + file;
    const body = await fetchText(url);
    const path = '/pkg/' + pkg + '/' + file;
    const dir = path.slice(0, path.lastIndexOf('/'));
    runtime.FS.mkdirTree(dir);
    runtime.FS.writeFile(path, body);
  }
}

async function initRuntime() {
  if (ready) return;
  progress('Downloading the Pyodide Python runtime…', { phase: 'pyodide' });
  const indexURL = await resolveIndexURL();
  if (typeof loadPyodide !== 'function') {
    importScripts(indexURL + 'pyodide.js');
  }
  pyodide = await loadPyodide({
    indexURL,
    stdout: (text) => { if (text && String(text).trim()) progress(String(text).trim(), { phase: 'python' }); },
    stderr: (text) => { if (text && String(text).trim()) progress(String(text).trim(), { phase: 'python' }); }
  });
  progress('Loading NumPy, SciPy, pandas, Matplotlib, and h5py…', { phase: 'packages' });
  await pyodide.loadPackage(LOAD_PACKAGES);
  progress('Installing MNE and report validators…', { phase: 'mne' });
  await pyodide.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(MICROPIP_PACKAGES)}, keep_going=True)
`);
  progress('Importing Neurobuddy v0.7.1 modules…', { phase: 'modules' });
  await installPythonModules(pyodide);
  await pyodide.runPythonAsync(`
import os, sys
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MNE_DATA'] = '/tmp/mne-data'
os.environ['HOME'] = '/home/pyodide'
os.makedirs('/tmp/mne-data', exist_ok=True)
sys.path.insert(0, '/pkg')
import matplotlib
matplotlib.use('Agg')
import mne
mne.set_log_level('ERROR')
from neurobuddy_v2 import browser_entry, __version__
`);
  ready = true;
  const versions = pyodide.runPython(`
import json, numpy, scipy, pandas, matplotlib, h5py, mne
from neurobuddy_v2 import __version__
json.dumps({
  'neurobuddy': __version__,
  'mne': mne.__version__,
  'numpy': numpy.__version__,
  'scipy': scipy.__version__,
  'pandas': pandas.__version__,
  'matplotlib': matplotlib.__version__,
  'h5py': h5py.__version__,
})
`);
  post({ type: 'ready', versions: JSON.parse(versions) });
}

function writeFiles(fsRoot, files) {
  pyodide.FS.mkdirTree(fsRoot);
  for (const file of files) {
    const rel = String(file.path || file.name || '').replace(/^\/+/, '');
    if (!rel || rel.includes('..')) throw new Error('Unsafe worker path');
    const full = fsRoot + '/' + rel;
    pyodide.FS.mkdirTree(full.slice(0, full.lastIndexOf('/')) || fsRoot);
    const bytes = new Uint8Array(file.buffer);
    pyodide.FS.writeFile(full, bytes);
  }
}

function readOutputs(dir, relativePaths) {
  const artifacts = [];
  for (const rel of relativePaths || []) {
    const full = dir + '/' + rel;
    try {
      const data = pyodide.FS.readFile(full);
      const copy = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
      artifacts.push({ path: rel, buffer: copy });
    } catch {
      /* missing optional figure */
    }
  }
  return artifacts;
}

function rmTree(path) {
  try {
    const stat = pyodide.FS.analyzePath(path);
    if (!stat.exists) return;
    const walk = (p) => {
      const info = pyodide.FS.lookupPath(p);
      if (!info.node) return;
      if (pyodide.FS.isDir(info.node.mode)) {
        for (const name of pyodide.FS.readdir(p)) {
          if (name === '.' || name === '..') continue;
          walk(p + '/' + name);
        }
        pyodide.FS.rmdir(p);
      } else {
        pyodide.FS.unlink(p);
      }
    };
    walk(path);
  } catch { /* already cleaned */ }
}

async function analyze(job) {
  cancelFlag = false;
  currentJob = job.id;
  const work = '/tmp/nb/' + job.id;
  const sourceRoot = work + '/in';
  const outRoot = work + '/out';
  pyodide.FS.mkdirTree(work);
  try {
    if (job.kind === 'fingerprint') {
      writeFiles(sourceRoot, job.files);
      const info = await pyodide.runPythonAsync(`
from neurobuddy_v2.browser_entry import fingerprint
import json
json.dumps(fingerprint(${JSON.stringify(sourceRoot)}))
`);
      return { result: JSON.parse(info), artifacts: [] };
    }
    if (job.kind === 'single') {
      writeFiles(sourceRoot, job.files);
      progress('Running Neurobuddy pipeline.process()…', { phase: 'analyze', jobId: job.id });
      const payload = JSON.stringify({
        source: sourceRoot,
        output: outRoot,
        artifact_mode: job.options.artifact_mode || 'legacy',
        mains_frequency_hz: job.options.mains_frequency_hz || 60,
        task_selected: job.options.task_selected || 'unspecified'
      });
      const raw = await pyodide.runPythonAsync(`
from neurobuddy_v2.browser_entry import run_single
import json
cfg = json.loads(${JSON.stringify(payload)})
json.dumps(run_single(cfg['source'], cfg['output'], artifact_mode=cfg['artifact_mode'],
                      mains_frequency_hz=float(cfg['mains_frequency_hz']),
                      task_selected=cfg['task_selected']))
`);
      const result = JSON.parse(raw);
      const artifacts = readOutputs(outRoot, result.outputs);
      delete result.outputs;
      return { result, artifacts };
    }
    if (job.kind === 'athlete') {
      const bases = [];
      (job.baselines || []).forEach((rec, i) => {
        const dir = sourceRoot + '/baseline/' + String(i).padStart(2, '0');
        writeFiles(dir, rec.files);
        bases.push(dir);
      });
      const testDir = sourceRoot + '/test';
      writeFiles(testDir, job.test.files);
      progress('Running longitudinal athlete comparison…', { phase: 'analyze', jobId: job.id });
      const payload = JSON.stringify({
        baselines: bases,
        test: testDir,
        output: outRoot,
        team_id: job.team_id,
        athlete_id: job.athlete_id,
        artifact_mode: job.options.artifact_mode || 'legacy',
        mains_frequency_hz: job.options.mains_frequency_hz || 60,
        min_baselines: job.options.min_baselines
      });
      const raw = await pyodide.runPythonAsync(`
from neurobuddy_v2.browser_entry import run_athlete
import json
cfg = json.loads(${JSON.stringify(payload)})
json.dumps(run_athlete(cfg['baselines'], cfg['test'], cfg['output'],
                       team_id=cfg['team_id'], athlete_id=cfg['athlete_id'],
                       artifact_mode=cfg['artifact_mode'],
                       mains_frequency_hz=float(cfg['mains_frequency_hz']),
                       min_baselines=cfg.get('min_baselines')))
`);
      const result = JSON.parse(raw);
      const artifacts = readOutputs(outRoot, result.outputs);
      delete result.outputs;
      return { result, artifacts };
    }
    throw new Error('Unknown analysis kind: ' + job.kind);
  } finally {
    rmTree(work);
    try { pyodide.runPython('import gc; gc.collect()'); } catch { /* ignore */ }
    currentJob = null;
  }
}

self.onmessage = async (event) => {
  const msg = event.data || {};
  try {
    if (msg.type === 'init') {
      await initRuntime();
      return;
    }
    if (msg.type === 'cancel') {
      cancelFlag = true;
      post({ type: 'cancelled', id: msg.id || currentJob });
      return;
    }
    if (msg.type === 'analyze') {
      if (!ready) await initRuntime();
      const done = await analyze(msg);
      const transfer = done.artifacts.map((a) => a.buffer);
      post({ type: 'result', id: msg.id, result: done.result, artifacts: done.artifacts }, transfer);
      return;
    }
    post({ type: 'error', id: msg.id, error: 'Unknown worker message' });
  } catch (err) {
    post({
      type: 'error',
      id: msg.id,
      error: (err && err.message) ? err.message : String(err),
      stack: err && err.stack
    });
  }
};
