#!/usr/bin/env node
/**
 * Phase 2/3/7: load Pyodide in Node, install the pinned scientific stack,
 * import neurobuddy_v2, and process the representative rest FIF.
 */
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const fixture = join(here, 'fixtures', 'sub-val_ses-01_task-rest_eeg.fif');
const pinned = JSON.parse(await readFile(join(root, 'pyodide/pinned-packages.json'), 'utf8'));
const modules = JSON.parse(await readFile(join(root, 'pyodide/python-modules.json'), 'utf8'));

const { loadPyodide } = await import('pyodide');
const localIndex = resolve(root, 'node_modules/pyodide');
const packageBaseUrl = `https://cdn.jsdelivr.net/pyodide/v${pinned.pyodide}/full/`;
console.log('Loading Pyodide', pinned.pyodide);
const pyodide = await loadPyodide({ indexURL: localIndex, packageBaseUrl });
console.log('Loading numpy/scipy/matplotlib/pandas/h5py');
await pyodide.loadPackage(['numpy', 'scipy', 'matplotlib', 'pandas', 'h5py', 'micropip', 'packaging']);
const micropipPkgs = Object.entries(pinned.micropip).map(([name, version]) => `${name}==${version}`);
console.log('micropip', micropipPkgs.join(', '));
await pyodide.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(micropipPkgs)}, keep_going=True)
`);
pyodide.FS.mkdirTree('/pkg/' + modules.package);
for (const file of modules.files) {
  const body = await readFile(join(root, modules.package, file));
  const path = '/pkg/' + modules.package + '/' + file;
  pyodide.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')));
  pyodide.FS.writeFile(path, body);
}
await pyodide.runPythonAsync(`
import os, sys
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MNE_DATA'] = '/tmp/mne-data'
os.makedirs('/tmp/mne-data', exist_ok=True)
sys.path.insert(0, '/pkg')
import matplotlib
matplotlib.use('Agg')
import mne, numpy, scipy, pandas, h5py
mne.set_log_level('ERROR')
from neurobuddy_v2 import __version__, browser_entry
print('neurobuddy', __version__)
print('mne', mne.__version__)
print('numpy', numpy.__version__)
print('scipy', scipy.__version__)
`);

const fif = await readFile(fixture);
pyodide.FS.mkdirTree('/in');
pyodide.FS.writeFile('/in/sub-val_ses-01_task-rest_eeg.fif', fif);
pyodide.FS.mkdirTree('/out');
console.log('Running fingerprint + pipeline.process');
const raw = await pyodide.runPythonAsync(`
import json, time
from neurobuddy_v2.browser_entry import fingerprint, run_single
started = time.time()
info = fingerprint('/in')
result = run_single('/in', '/out', artifact_mode='legacy', task_selected='unspecified', player_frames=80)
result['fingerprint'] = info
result['elapsed_s'] = time.time() - started
json.dumps(result)
`);
const result = JSON.parse(raw);
const outDir = join(here, 'fixtures');
await mkdir(outDir, { recursive: true });
await writeFile(join(outDir, 'pyodide_report.json'), JSON.stringify(result, null, 2));
const rec = result.analysis.recording;
console.log('status', result.analysis.processing_status);
console.log('sfreq', rec.sample_rate_hz, 'channels', rec.n_channels, 'duration', rec.duration_s);
console.log('elapsed_s', result.elapsed_s);
if (rec.sample_rate_hz !== 256) {
  throw new Error('Sampling frequency changed: ' + rec.sample_rate_hz);
}
if (rec.n_channels !== 4) {
  throw new Error('Channel count changed: ' + rec.n_channels);
}
console.log('OK');
