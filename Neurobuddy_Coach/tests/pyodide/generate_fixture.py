"""Write a tiny deterministic FIF used by native vs Pyodide validation."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import mne


def write_rest_fif(path: Path, *, sfreq: float = 256.0, duration_s: float = 2.0) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n_times = int(sfreq * duration_s)
    times = np.arange(n_times) / sfreq
    rng = np.random.default_rng(20261123)
    names = ["C3", "C4", "Cz", "Oz"]
    data = np.zeros((len(names), n_times), dtype=np.float64)
    for i, hz in enumerate((10.0, 12.0, 8.0, 20.0)):
        data[i] = 12e-6 * np.sin(2 * np.pi * hz * times) + 0.4e-6 * rng.standard_normal(n_times)
    info = mne.create_info(names, sfreq, ch_types="eeg")
    raw = mne.io.RawArray(data, info, verbose="ERROR")
    raw.set_meas_date(None)
    raw.save(path, overwrite=True, verbose="ERROR")
    return path


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "fixtures" / "sub-val_ses-01_task-rest_eeg.fif"
    write_rest_fif(target)
    print(target)
