# Neurobuddy scientific pipeline performance optimization

## Goal and scientific invariance

This build optimizes performance *without intentionally changing EEG input handling, filtering, feature algorithms, artifact detection thresholds, routing, sleep analysis, numerical reports or generated visualization data.* This remains a scientific research prototype, not a validated clinical tool.

- The unchanged data contract uses `schema_version: 2.0.0`.
- The `neurobuddy_v2.__version__` report value remains `0.7.0-research` deliberately: downstream longitudinal comparisons should not treat identical measurements as different processing pipelines merely because execution became faster. The distribution package is `0.7.1`.
- Experimental artifact screening remains optional (`--artifact-mode experimental`); the default remains legacy.
- No signal resampling, approximation, threshold change, caching of EEG science, GPU requirement, task parallelism, plot degradation or skipped report asset was introduced.

## Changes

1. **Vectorized artifact screening.** The 1-second/4-second sliding window grids, sample boundaries, overlap, detrending and PSD estimator are unchanged. Instead of calling SciPy's periodogram separately for every time window, `_window_batches` reads a bounded channel block, creates views into the same samples and computes many window spectra in one call. Derived values and event records retain the original ordering and precision in the tested cases. Peak-to-peak, RMS and jumps are also evaluated by NumPy across batches.
2. **Vectorized 50/60 Hz spectral check.** `_line_prominences_batch` uses the same frequency bins and target/background definitions, including handling of nonfinite windows and unassessable Nyquist conditions. Intermediate ratios can differ at the last few IEEE-754 bits owing to FFT batching, with differences below 1e-12 on tests. A rare near-exact-threshold decision can theoretically differ, so bitwise identity is **not** guaranteed for every possible signal.
3. **Compiled JSON Schema validation.** The same `report.schema.json` is validated by `fastjsonschema` using a cached compiled function, removing a large cold-import overhead. The previous `jsonschema.Draft202012Validator` remains a fallback when the optional fast package is not installed. Valid output structures are unaffected. Error text can differ between validator implementations.

## Reproducible benchmark

Host used: 5 visible CPUs, Python 3.13.5, MNE 1.11.0, SciPy 1.17.0, NumPy 2.3.5, `OPENBLAS_NUM_THREADS=1`, `MPLBACKEND=Agg`. Test: synthetic 120-second 8-channel 256 Hz FIF, fixed seed, GENERAL EEG, experimental artifact mode, 1,500-player-frame cap, complete report including images and ZIP. These time measurements start immediately before `process()` inside a fresh interpreter. Interpreter startup and import of `neurobuddy_v2.pipeline` are excluded; the first schema validator import inside `process()` is included.

| Metric | Original v0.7.0 | Optimized build | Change |
|---|---:|---:|---:|
| Direct artifact detector, cProfile wall time | 1.245 s | 0.164 s | 7.59x faster |
| End-to-end non-streaming, run 1 | 3.199 s | 1.518 s | 2.11x faster |
| End-to-end non-streaming, run 2 | 3.182 s | 1.645 s | 1.93x faster |
| End-to-end forced streaming, run 1 | 3.066 s | 1.418 s | 2.16x faster |

**Output comparisons:** In the two recorded processing modes, `report.json` matched recursively *exactly* after removing only `provenance.created_utc`. `artifact_events.csv`, `player_data.json` and `waveform_raw_vs_filtered.png` were byte-identical between the baseline and optimized process runs. Additionally, 36 direct artifact-detector tests using varying sampling rates, durations, seeds and injected contamination yielded identical event/summary result dictionaries. These results demonstrate equivalence for tested cases, not an absolute guarantee for all inputs.

For verification on your computer, place the v0.7.0 original next to this folder and run:

```bash
python benchmarks/benchmark_runtime.py \
  --baseline ../Neurobuddy_v0.7.0_Artifact_Research \
  --optimized .
python benchmarks/benchmark_runtime.py \
  --baseline ../Neurobuddy_v0.7.0_Artifact_Research \
  --optimized . --streaming
python -m pytest tests/ -q
```

## Remaining speed limitations

- MNE file decoding, FIR filtering, detailed Matplotlib plot rendering, ZIP compression, sleep-model loading and optional automated staging remain unchanged. Their proportion of runtime rises after optimizing the artifact detector.
- Multiple separately processed athlete recordings still run sequentially, avoiding uncontrolled peak memory and potential thread-safety complications.
- The on-disk EEG format, number of channels, duration, number of generated figures, processor, SSD and OS materially affect throughput. The improvement can be smaller or larger than the above benchmark.
- Input data are not retained between runs and existing reports are fully regenerated. Accelerating repeat jobs with validated content-addressed caching would be a separate enhancement requiring provenance and invalidation policies.
- Real multi-hour sleep recordings were not supplied, and numerical end-to-end equivalence is not established for all physiological tasks on real datasets. Do not infer runtime or signal-quality improvements for those use cases from this synthetic benchmark alone.
