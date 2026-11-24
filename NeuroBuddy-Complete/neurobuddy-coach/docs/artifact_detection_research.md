# Neurobuddy artifact detection: code audit, implementation and limitations

Research build 0.7.0 based on user-supplied **Neurobuddy V2 v0.6.1** and *NeuroBuddy Artifact Detection Research* (20 November 2026 upload). The research document is a technical evidence review and progress report, **not an independently validated artifact-detection paper**. Its reported 210 synthetic-recording experiment was *not* reproduced by this build. All metrics in `results/artifacts/` come from a **new, separately executed synthetic benchmark** in this source tree.

## Existing code limitations (verified against source)

| Location | Actual existing behavior | Limitation |
|---|---|---|
| `legacy_combined.Settings` | 1–45 Hz filtered quality, global transient threshold 6 SD; default mains 60 Hz but *already configurable* | Global z-scores can miss local contamination. A user must select 50/60 Hz as appropriate; `Settings` already had mains config in v0.6.1. |
| `legacy_combined.artifact_audit` | Global filtered EEG Z-scores; first 50 transient timestamps; per-channel line-noise and whole-record electrode flags | Not a time-local event catalog; cannot discriminate physiological sources; no calibrated accuracy. |
| `quality_audit` | Whole-recording low variability, possible clipping, uncalibrated difference-SNR proxy | Short dropouts and plateau segments may go unnoticed. |
| `line_noise_audit` | Raw periodogram peak around configured mains frequency, local prominence | Unstable on short/low-resolution samples and can produce stochastic false positives. |
| `large_recordings.analyze_large` | Separate streaming approximations for quality/outliers | Not identical to full-recording IONM metrics; chunk boundary performance had not been established. |
| `analysis` task routes | Existing shared IONM trial screening and specialized ERP, motor, sleep computations | Artifact sources are not separated; automatic masking could delete legitimate task/physiology events. |
| `comparative.build_comparison` | Compatible per-recording metrics and mean/sample SD Z-score | Does not establish that input values are contamination-free. |
| `tests` | Route, comparison, streaming, sleep, figures and report regression | No real, independently labeled artifact event sensitivity/specificity study. |

## Implemented (optional research branch)

- New `neurobuddy_v2/artifact_detection.py` with `ArtifactConfig`, versioned event records, bounded raw reads and **absolute sample-aligned overlapping windows**. Used unchanged for standard and forced-streaming pipelines.
- Candidate **local dropouts**: peak-to-peak <=2 μV inside an otherwise substantially more variable channel. Short events that do not occupy enough of the 1-second window can be missed.
- Candidate **amplitude bursts**: local RMS >3× reference median, with 4–30 Hz spectral enrichment and increased 4–30 Hz band-limited RMS. This was added to reduce false flags on synthetic slow-wave controls; it can miss slow ocular/movement artifacts and may flag actual task-related activity.
- Candidate **abrupt sample changes**: local maximal derivative above both 20 μV/sample and 8× channel median. A steep neural event may look similar.
- Candidate **mains interference**: 4-second raw EEG periodograms (Hann window), comparison with nearby spectral background, and two adjacent positive checks. Explicit 50/60 Hz config. Returns `unassessable` if Nyquist/duration insufficient.
- Candidate **nonfinite samples**: localized in window intervals, no interpolation.
- Overlapping windows of the same candidate class are merged deterministically. Each event contains channel, start/end times, evidence, thresholds, detector version, and explicit *uncalibrated, requires review* status. Quality masks are compact interval lists, not large per-sample bitmaps.
- `process(..., artifact_mode='experimental', mains_frequency_hz=50|60)` and equivalent CLI flags. Default remains **`legacy`**. The legacy mode does **not** add new detectors. Existing EEG measurements and specialized analyses are not corrected, masked, or recomputed from exclusions.
- Experimental reports include `quality.artifact_detection`, `artifact_events.csv`, full HTML tables/summaries, detector configuration and versioned provenance in JSON and portable ZIP.
- Athlete comparative reports additionally export `artifact_quality_provenance.csv` and attach the quality summaries. **No baseline is silently excluded and no Z-score arithmetic is changed.** Quality screening does not establish comparison eligibility.
- Scientific regression coverage verifies source data invariance, clean controls, event localization, explicit unassessable outcomes, 50 Hz support, normal/streaming parity, default backward compatibility, ZIP/HTML/CSV output and unaffected comparative results.

## Reproduce

```bash
python -m pip install -r requirements.txt
python -m pytest tests/ -q
python -m neurobuddy_v2 path/to/sub-01_task-rest_eeg.fif --artifact-mode experimental --mains-frequency 50 --output reports/artifacts
python -m neurobuddy_v2 path/to/sub-01_task-rest_eeg.fif --output reports/legacy
PYTHONPATH=. python experiments/benchmark_artifacts.py --seeds 12 --seed-offset 0 --output results/artifacts/development
PYTHONPATH=. python experiments/benchmark_artifacts.py --seeds 12 --seed-offset 1000 --output results/artifacts/heldout
```

For multi-recording athlete comparison, add `--artifact-mode experimental --mains-frequency 50` to the existing `--baseline ... --test ... --team ... --athlete ...` invocation. Mains frequency is recording-wide for now; sessions from different 50/60 Hz environments must be run or configured separately rather than supplying one incorrect frequency for a whole batch.

## Fresh benchmark observations and limitations

Each 108-recording set has **12 different synthetic random backgrounds × 9 scenarios**: clean periodic EEG, flatline, RMS burst, abrupt step, spike, 50 Hz, 60 Hz, high-amplitude slow-wave-like *clean* control, and spindle-like *clean* control. Each set has 72 injected-artifact recordings and 36 controls. The same detector thresholds were applied to seed-offset 1000 after examining seed-offset 0. The backgrounds and artifacts still come from the same simulation family, so this is **not an independently sourced or participant-level held-out study**.

| Recording-level measure | Baseline (dev) | Experimental (dev) | Baseline (separate seeds) | Experimental (separate seeds) |
|---|---:|---:|---:|---:|
| TP / FN | 43 / 29 | 69 / 3 | 48 / 24 | 70 / 2 |
| FP / TN | 2 / 34 | 0 / 36 | 4 / 32 | 1 / 35 |
| Precision | .956 | 1.000 | .923 | .986 |
| Recall | .597 | .958 | .667 | .972 |
| F1 | .735 | .979 | .774 | .979 |
| Best-interval IoU, average across positives | Not measured | .605 | Not measured | .616 |
| Known-clean time retained* | Not measured | .974 | Not measured | .974 |

*The clean-time retention value means the fraction of samples outside **injected** intervals that had no candidate overlap; this is NOT an actual real-world clean-data retention estimate. For the separate-seed run, the implementation also flagged ~94.7 seconds per hour of known-clean time around simulated events. This is a material cost and limits automatic use. The few flatline misses occur chiefly for short intervals that never fully occupy an analysis window. Exact values and per-scenario results are in `results/artifacts/{development,heldout}/summary.json` and `recording_level.csv`.

**Do not report these numbers as clinical, athlete-readiness, device-generalizable, real EEG, artifact-specific event-level precision, or proof of superior downstream ERP/ERD statistics.** A binary recording-level test can score a positive even when the detected artifact class is wrong. Interval overlaps are class-agnostic exploratory metrics. The baseline global flagger does not output equivalent event intervals, so matched class-specific event-level evaluation of baseline vs new method remains pending.

## Explicitly not implemented

- Automatic artifact removal, cleaning, ICA/ICLabel, ASR, AutoReject, channel interpolation or automatically rejected sleep/ERP/motor trials.
- Validated EOG-assisted ocular source inference, EMG separation, electrode fault causal classification or 2-reviewer real EEG annotation study.
- Source-level clinical or athletic readiness inference.
- Fully validated sample rate/channel/device portability, reference compatibility or established false alarm budgets.
- Real PSG sleep wave/spindle false-positive benchmarking, matched ERP/ERD downstream feature testing, and production-scale peak-memory benchmarking.
- The coach website/Repository is **not** part of this ZIP, which contains the standalone scientific pipeline only.

## Next scientific steps before enabling masks downstream

1. Acquire appropriate independently annotated real EEG, permissions, montage and acquisition metadata. Separate development/test subjects and keep held-out subjects untouched until thresholds are frozen.
2. Have at least two blinded expert reviewers identify temporal intervals and artifact types. Measure disagreement and reconcile by protocol.
3. Report type-specific TP/FP/FN, event overlap, onset/offset errors, sensitivity, precision, false flagged seconds/hour, data retention, and subgroup performance by sleep/motor/oddball task.
4. Verify reference-channel/EOG requirements. Never infer blink/EMG cause from morphology alone on sparse-channel devices.
5. Compare downstream P300, motor ERD/ERS, sleep spectral features and longitudinal Z-scores against vetted clean references. Evaluate possible bias introduced by masking.
6. Benchmark wall time, peak RSS, long-duration datasets and chunk-boundary agreement across file formats and channel counts.
7. Establish documented acceptable false-positive and clean-data-loss budgets. Only then assess opt-in trial masks or separate derived corrected recordings with full provenance.
