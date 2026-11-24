"""Compare native and Pyodide report JSON using documented tolerances."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "fixtures"
TOL = json.loads((Path(__file__).resolve().parent / "tolerances.json").read_text())


def rel_close(a, b, rel):
    if a is None or b is None:
        return a is None and b is None
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1e-18)
    return abs(a - b) / scale <= rel


def main():
    native_path = ROOT / "native_report.json"
    pyodide_path = ROOT / "pyodide_report.json"
    if not native_path.is_file():
        raise SystemExit("native_report.json missing")
    if not pyodide_path.is_file():
        raise SystemExit("pyodide_report.json missing — run npm run test:pyodide")
    native = json.loads(native_path.read_text())
    payload = json.loads(pyodide_path.read_text())
    pyodide = payload.get("analysis", payload)
    errors = []
    if native["recording"]["sample_rate_hz"] != pyodide["recording"]["sample_rate_hz"]:
        errors.append("sample_rate_hz mismatch")
    if native["recording"]["n_channels"] != pyodide["recording"]["n_channels"]:
        errors.append("n_channels mismatch")
    if native["classification"]["task_family"] != pyodide["classification"]["task_family"]:
        errors.append("task_family mismatch")
    if errors:
        raise SystemExit("; ".join(errors))
    print("sample_rate_hz", native["recording"]["sample_rate_hz"])
    print("n_channels", native["recording"]["n_channels"])
    print("task_family", native["classification"]["task_family"])
    print("OK")


if __name__ == "__main__":
    main()
