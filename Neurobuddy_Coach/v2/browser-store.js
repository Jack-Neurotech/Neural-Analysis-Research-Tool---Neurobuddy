/* IndexedDB + Origin Private File System for Neurobuddy browser-native data.
   Metadata stays in IDB. EEG bytes prefer OPFS, then IDB blobs. */
(() => {
  'use strict';
  const DB_NAME = 'neurobuddy-pyodide-v1';
  const DB_VERSION = 1;
  const META_KEY = 'workspace';
  const SIGNALS = ['.set', '.edf', '.bdf', '.vhdr', '.fif', '.fif.gz'];

  function now() { return new Date().toISOString(); }
  function uid() {
    return (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    }));
  }
  function isSignal(name) {
    return SIGNALS.some((ext) => String(name || '').toLowerCase().endsWith(ext));
  }

  function emptyWorkspace() {
    return {
      teams: [],
      athletes: [],
      recordings: [],
      files: [],
      jobs: [],
      prefs: { artifact_mode: 'experimental', mains_frequency_hz: 60 }
    };
  }

  let dbPromise = null;
  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
        if (!db.objectStoreNames.contains('blobs')) db.createObjectStore('blobs');
        if (!db.objectStoreNames.contains('artifacts')) db.createObjectStore('artifacts');
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('IndexedDB unavailable'));
    });
    return dbPromise;
  }

  function idbReq(req) {
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function kvGet(key) {
    const db = await openDb();
    return idbReq(db.transaction('kv', 'readonly').objectStore('kv').get(key));
  }
  async function kvSet(key, value) {
    const db = await openDb();
    await idbReq(db.transaction('kv', 'readwrite').objectStore('kv').put(value, key));
  }

  async function loadWorkspace() {
    const stored = await kvGet(META_KEY);
    if (stored && Array.isArray(stored.teams) && Array.isArray(stored.jobs)) return stored;
    const empty = emptyWorkspace();
    await kvSet(META_KEY, empty);
    return empty;
  }
  async function saveWorkspace(ws) {
    await kvSet(META_KEY, ws);
  }

  let opfsRoot = null;
  async function opfs() {
    if (opfsRoot) return opfsRoot;
    if (!navigator.storage || !navigator.storage.getDirectory) return null;
    try {
      opfsRoot = await navigator.storage.getDirectory();
      return opfsRoot;
    } catch {
      return null;
    }
  }

  async function ensureDir(root, parts) {
    let dir = root;
    for (const part of parts) {
      dir = await dir.getDirectoryHandle(part, { create: true });
    }
    return dir;
  }

  async function writeBlob(kind, id, name, buffer) {
    const bytes = buffer instanceof ArrayBuffer ? buffer : (buffer.buffer || buffer);
    const root = await opfs();
    if (root) {
      try {
        const dir = await ensureDir(root, [kind, id]);
        const handle = await dir.getFileHandle(safeName(name), { create: true });
        const writable = await handle.createWritable();
        await writable.write(bytes);
        await writable.close();
        return { storage: 'opfs', size: byteLength(bytes) };
      } catch { /* fall through to IDB */ }
    }
    const db = await openDb();
    const key = kind + '/' + id + '/' + name;
    await idbReq(db.transaction('blobs', 'readwrite').objectStore('blobs').put(bytes, key));
    return { storage: 'idb', size: byteLength(bytes) };
  }

  async function readBlob(kind, id, name, storage) {
    if (storage !== 'idb') {
      const root = await opfs();
      if (root) {
        try {
          const dir = await ensureDir(root, [kind, id]);
          const handle = await dir.getFileHandle(safeName(name));
          const file = await handle.getFile();
          return await file.arrayBuffer();
        } catch {
          if (storage === 'opfs') throw new Error('EEG file missing from browser storage: ' + name);
        }
      }
    }
    const db = await openDb();
    const key = kind + '/' + id + '/' + name;
    const value = await idbReq(db.transaction('blobs', 'readonly').objectStore('blobs').get(key));
    if (!value) throw new Error('EEG file missing from browser storage: ' + name);
    return value instanceof ArrayBuffer ? value : value.buffer;
  }

  async function deleteBlob(kind, id, name, storage) {
    if (storage !== 'idb') {
      const root = await opfs();
      if (root) {
        try {
          const dir = await ensureDir(root, [kind, id]);
          await dir.removeEntry(safeName(name));
        } catch { /* already gone */ }
      }
    }
    const db = await openDb();
    const key = kind + '/' + id + '/' + name;
    await idbReq(db.transaction('blobs', 'readwrite').objectStore('blobs').delete(key));
  }

  async function deletePrefix(kind, id) {
    const root = await opfs();
    if (root) {
      try {
        const parent = await ensureDir(root, [kind]);
        await parent.removeEntry(id, { recursive: true });
      } catch { /* missing */ }
    }
    const db = await openDb();
    const tx = db.transaction('blobs', 'readwrite');
    const store = tx.objectStore('blobs');
    const prefix = kind + '/' + id + '/';
    const keys = await idbReq(store.getAllKeys());
    for (const key of keys) {
      if (String(key).startsWith(prefix)) store.delete(key);
    }
    await new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  function safeName(name) {
    const base = String(name || '').split(/[/\\]/).pop();
    if (!base || base === '.' || base === '..' || base.includes('\0')) {
      throw new Error('Unsafe filename');
    }
    return base;
  }
  function byteLength(bytes) {
    if (!bytes) return 0;
    if (typeof bytes.byteLength === 'number') return bytes.byteLength;
    return bytes.length || 0;
  }

  async function putArtifact(jobId, path, buffer, mime) {
    const db = await openDb();
    const key = jobId + '/' + path;
    await idbReq(db.transaction('artifacts', 'readwrite').objectStore('artifacts').put({
      mime: mime || mimeOf(path),
      buffer
    }, key));
  }
  async function getArtifact(jobId, path) {
    const db = await openDb();
    return idbReq(db.transaction('artifacts', 'readonly').objectStore('artifacts').get(jobId + '/' + path));
  }
  async function artifactKeys(jobId) {
    const db = await openDb();
    const keys = await idbReq(db.transaction('artifacts', 'readonly').objectStore('artifacts').getAllKeys());
    const prefix = jobId + '/';
    return keys.filter((key) => String(key).startsWith(prefix)).map((key) => String(key).slice(prefix.length));
  }
  async function deleteArtifacts(jobId) {
    const db = await openDb();
    const tx = db.transaction('artifacts', 'readwrite');
    const store = tx.objectStore('artifacts');
    const prefix = jobId + '/';
    const keys = await idbReq(store.getAllKeys());
    for (const key of keys) {
      if (String(key).startsWith(prefix)) store.delete(key);
    }
    await new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  function mimeOf(path) {
    const lower = String(path).toLowerCase();
    if (lower.endsWith('.html')) return 'text/html; charset=utf-8';
    if (lower.endsWith('.json')) return 'application/json';
    if (lower.endsWith('.csv')) return 'text/csv';
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.zip')) return 'application/zip';
    if (lower.endsWith('.svg')) return 'image/svg+xml';
    return 'application/octet-stream';
  }

  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      table[i] = c;
    }
    return table;
  })();
  function crc32(bytes) {
    const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    let c = 0xffffffff;
    for (let i = 0; i < view.length; i++) c = CRC_TABLE[(c ^ view[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  function encodeUtf8(text) {
    return new TextEncoder().encode(text);
  }

  function zipStore(files) {
    const locals = [];
    const centrals = [];
    let offset = 0;
    for (const file of files) {
      const name = encodeUtf8(file.name);
      const data = file.data instanceof Uint8Array ? file.data : new Uint8Array(file.data);
      const crc = crc32(data);
      const local = new Uint8Array(30 + name.length + data.length);
      const view = new DataView(local.buffer);
      view.setUint32(0, 0x04034b50, true);
      view.setUint16(4, 20, true);
      view.setUint16(8, 0, true);
      view.setUint16(10, 0, true);
      view.setUint16(12, 0, true);
      view.setUint32(14, crc, true);
      view.setUint32(18, data.length, true);
      view.setUint32(22, data.length, true);
      view.setUint16(26, name.length, true);
      local.set(name, 30);
      local.set(data, 30 + name.length);
      locals.push(local);
      const central = new Uint8Array(46 + name.length);
      const cv = new DataView(central.buffer);
      cv.setUint32(0, 0x02014b50, true);
      cv.setUint16(4, 20, true);
      cv.setUint16(6, 20, true);
      cv.setUint32(16, crc, true);
      cv.setUint32(20, data.length, true);
      cv.setUint32(24, data.length, true);
      cv.setUint16(28, name.length, true);
      cv.setUint32(42, offset, true);
      central.set(name, 46);
      centrals.push(central);
      offset += local.length;
    }
    const centralSize = centrals.reduce((n, c) => n + c.length, 0);
    const end = new Uint8Array(22);
    const ev = new DataView(end.buffer);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(8, files.length, true);
    ev.setUint16(10, files.length, true);
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);
    const total = offset + centralSize + 22;
    const out = new Uint8Array(total);
    let pos = 0;
    for (const part of locals) { out.set(part, pos); pos += part.length; }
    for (const part of centrals) { out.set(part, pos); pos += part.length; }
    out.set(end, pos);
    return out;
  }

  function unzipStore(buffer) {
    const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const files = [];
    let offset = 0;
    while (offset + 4 <= bytes.length && view.getUint32(offset, true) === 0x04034b50) {
      const nameLen = view.getUint16(offset + 26, true);
      const extraLen = view.getUint16(offset + 28, true);
      const method = view.getUint16(offset + 8, true);
      const comp = view.getUint32(offset + 18, true);
      const name = new TextDecoder().decode(bytes.subarray(offset + 30, offset + 30 + nameLen));
      const start = offset + 30 + nameLen + extraLen;
      if (method !== 0) throw new Error('Backup uses an unsupported ZIP compression method.');
      files.push({ name, data: bytes.slice(start, start + comp) });
      offset = start + comp;
    }
    return files;
  }

  async function persistPermission() {
    if (navigator.storage && navigator.storage.persist) {
      try { return await navigator.storage.persist(); } catch { return false; }
    }
    return false;
  }
  async function storageInfo() {
    if (!navigator.storage || !navigator.storage.estimate) return null;
    try {
      const est = await navigator.storage.estimate();
      return { usage: est.usage || 0, quota: est.quota || 0, persisted: await persistPermission() };
    } catch {
      return null;
    }
  }

  window.NeurobuddyStore = {
    SIGNALS, isSignal, now, uid, emptyWorkspace, loadWorkspace, saveWorkspace,
    writeBlob, readBlob, deleteBlob, deletePrefix, putArtifact, getArtifact, artifactKeys, deleteArtifacts,
    mimeOf, zipStore, unzipStore, persistPermission, storageInfo, encodeUtf8, safeName
  };
})();
