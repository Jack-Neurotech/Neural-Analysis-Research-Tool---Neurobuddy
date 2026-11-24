"""Experimental, non-destructive EEG artifact *candidate* localization.

Research screening only. Signals, trials, and downstream features are NEVER
changed. All windows use absolute sample indices so normal/streaming calls have
identical boundaries. No claim of calibrated probabilities or artifact causes.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import defaultdict
import math
import numpy as np
from scipy import signal

DETECTOR_VERSION = 'window-eeg-0.1.0'


@dataclass(frozen=True)
class ArtifactConfig:
    window_seconds: float = 1.0
    hop_seconds: float = 0.5
    read_chunk_seconds: float = 30.0
    flatline_ptp_uv: float = 2.0
    flatline_reference_ratio: float = 4.0
    rms_burst_ratio: float = 3.0
    rms_min_4_30hz_fraction: float = 0.40
    rms_band_reference_ratio: float = 2.5
    max_jump_uv: float = 20.0
    max_jump_reference_ratio: float = 8.0
    minimum_reference_windows: int = 5
    mains_frequency_hz: float = 60.0
    line_window_seconds: float = 4.0
    line_hop_seconds: float = 2.0
    line_noise_prominence_ratio: float = 12.0
    line_min_consecutive_windows: int = 2

    def validate(self):
        if not 0 < self.hop_seconds <= self.window_seconds:
            raise ValueError('Artifact hop must be positive and not exceed window length.')
        if self.read_chunk_seconds < self.window_seconds or self.read_chunk_seconds < self.line_window_seconds:
            raise ValueError('Read chunk must be >= every detector window.')
        if not all(math.isfinite(v) and v > 0 for v in (
            self.window_seconds, self.hop_seconds, self.read_chunk_seconds,
            self.flatline_ptp_uv, self.flatline_reference_ratio,
            self.rms_burst_ratio, self.rms_min_4_30hz_fraction, self.rms_band_reference_ratio, self.max_jump_uv, self.max_jump_reference_ratio,
            self.line_window_seconds,
            self.line_hop_seconds, self.line_noise_prominence_ratio,
        )):
            raise ValueError('Artifact configuration contains nonpositive or non-finite values.')
        if self.rms_min_4_30hz_fraction > 1:
            raise ValueError('Power fraction threshold must be between 0 and 1.')
        if self.minimum_reference_windows < 3 or self.line_min_consecutive_windows < 1:
            raise ValueError('Insufficient reference or line-noise windows.')
        if self.mains_frequency_hz not in (50.0, 60.0):
            raise ValueError('Specify the recording mains frequency, 50 or 60 Hz.')


def _window_data(raw, channel: str, samples: int, hop: int, read_chunk_samples: int):
    """Emit absolute windows; bounded raw reads, even for lazy .set/.fdt files.

    Chunk boundaries are independent from the detector window grid. Read groups
    of whole windows; a window crossing a read boundary is never discarded.
    """
    n = int(raw.n_times)
    if n < samples:
        return
    # How many overlapping windows can be loaded in one bounded read?
    per_block = max(1, 1 + (read_chunk_samples - samples) // hop)
    windows = range(0, n - samples + 1, hop)
    it = iter(windows)
    while True:
        starts = []
        for _ in range(per_block):
            next_start = next(it, None)
            if next_start is None:
                break
            starts.append(next_start)
        if not starts:
            break
        first, stop = starts[0], starts[-1] + samples
        # Read one channel at a time to bound total memory usage.
        block = raw.get_data(picks=[channel], start=first, stop=stop)[0]
        for start in starts:
            off = start-first
            yield start, start+samples, block[off:off+samples]



def _window_batches(raw, channel: str, samples: int, hop: int, read_chunk_samples: int):
    """Yield overlapping windows in bounded batches, preserving absolute starts.

    One MNE read and one SciPy spectral call serve many identical windows.
    The sample grid, window shape, and detrend settings match ``_window_data``.
    This works for lazy recordings without loading a whole EEG into memory.
    """
    n = int(raw.n_times)
    if n < samples:
        return
    per_block = max(1, 1 + (read_chunk_samples - samples) // hop)
    total = 1 + (n - samples) // hop
    for i in range(0, total, per_block):
        count = min(per_block, total - i)
        starts = np.arange(i, i + count, dtype=np.int64) * hop
        first = int(starts[0])
        stop = int(starts[-1]) + samples
        block = raw.get_data(picks=[channel], start=first, stop=stop)[0]
        # View only. The spectral routine will copy iff necessary.
        views = np.lib.stride_tricks.sliding_window_view(block, samples)[::hop]
        yield starts, views[:count]


def _line_prominences_batch(data: np.ndarray, sfreq: float, mains: float):
    """Vectorized equivalent of ``_line_prominence`` for window rows."""
    count = len(data)
    if count == 0:
        return []
    if sfreq / 2 <= mains + 5 or data.shape[1] < 4:
        return [None] * count
    finite = np.all(np.isfinite(data), axis=1)
    result = [None] * count
    if not finite.any():
        return result
    f, spectra = signal.periodogram(data[finite], fs=sfreq, window='hann',
                                    detrend='linear', axis=-1)
    target = np.abs(f-mains) <= .75
    flank = (np.abs(f-mains) <= 5.) & (np.abs(f-mains) >= 1.25)
    if not np.any(target) or np.count_nonzero(flank) < 4:
        return result
    baselines = np.median(spectra[:, flank], axis=1)
    peaks = np.max(spectra[:, target], axis=1)
    for idx, background, peak in zip(np.flatnonzero(finite), baselines, peaks):
        if background > 0:
            result[int(idx)] = float(peak / background)
    return result

def _merge_intervals(items: list[dict], gap_s: float = 0.0) -> list[dict]:
    if not items:
        return []
    merged = []
    for event in sorted(items, key=lambda x:(x['channel'], x['artifact_type'], x['start_s'])):
        if merged and (merged[-1]['channel'], merged[-1]['artifact_type']) == (event['channel'], event['artifact_type']) and event['start_s'] <= merged[-1]['end_s'] + gap_s + 1e-9:
            previous = merged[-1]
            previous['end_s'] = max(previous['end_s'], event['end_s'])
            previous['window_count'] += event['window_count']
            # Preserve peak evidence rather than averaging away contamination.
            for key, value in event['feature_values'].items():
                if key.startswith('max_'):
                    previous['feature_values'][key] = max(previous['feature_values'].get(key, value), value)
                elif key.startswith('min_'):
                    previous['feature_values'][key] = min(previous['feature_values'].get(key, value), value)
        else:
            merged.append({**event, 'feature_values': dict(event['feature_values'])})
    return sorted(merged, key=lambda x:(x['start_s'], x['channel'], x['artifact_type']))


def _coverage(intervals, duration):
    if duration <= 0 or not intervals:
        return 0.0
    ordered = sorted((max(0.,a),min(duration,b)) for a,b in intervals if b>a)
    total = 0.
    lo = hi = None
    for a,b in ordered:
        if lo is None:
            lo,hi=a,b
        elif a<=hi:
            hi=max(hi,b)
        else:
            total+=hi-lo;lo,hi=a,b
    if lo is not None:
        total+=hi-lo
    return float(min(1.,total/duration))


def _line_prominence(x: np.ndarray, sfreq: float, mains: float):
    """Periodogram on unfiltered signal. Return assessable and observed ratio.

    The frequency ±0.75 Hz peak is compared with a ±5 Hz neighborhood excluding
    ±1 Hz. This is an exploratory peak heuristic, not a calibrated classifier.
    """
    if sfreq / 2 <= mains + 5:
        return None
    if len(x) < 4 or not np.all(np.isfinite(x)):
        return None
    freqs,power = signal.periodogram(x, fs=sfreq, window='hann', detrend='linear')
    target=(np.abs(freqs-mains)<=0.75)
    flank=(np.abs(freqs-mains)<=5.) & (np.abs(freqs-mains)>=1.25)
    if not np.any(target) or np.count_nonzero(flank)<4:
        return None
    baseline=float(np.median(power[flank]))
    peak=float(np.max(power[target]))
    if baseline<=0:
        return None
    return float(peak/baseline)


def detect_artifacts(raw, *, config: ArtifactConfig | None = None, recording_id: str | None = None) -> dict:
    """Return versioned candidate intervals, masks and explicit assessability.

    Normal and large EEG recordings invoke this exact same function. No raw or
    filtered MNE object is modified. Quality masks are annotation intervals,
    not automatically applied to EEG features or rejected trials.
    """
    cfg=config or ArtifactConfig()
    cfg.validate()
    sfreq=float(raw.info['sfreq'])
    duration=float(raw.n_times/sfreq)
    eeg_channels=[n for n,t in zip(raw.ch_names, raw.get_channel_types()) if t=='eeg']
    win=max(2,round(cfg.window_seconds*sfreq))
    hop=max(1,round(cfg.hop_seconds*sfreq))
    read=max(win,round(cfg.read_chunk_seconds*sfreq))
    line_win=max(2,round(cfg.line_window_seconds*sfreq))
    line_hop=max(1,round(cfg.line_hop_seconds*sfreq))
    notes=['Candidate artifact morphology is not a confirmed source classification.',
           'No signal correction, artifact subtraction, trial rejection or change to downstream EEG statistics is performed.',
           'Masks are advisory. Physiological slow waves, K-complexes and task events may overlap flagged intervals.',
           'High-RMS bursts need both 4–30 Hz spectral enrichment and elevated 4–30 Hz power relative to the channel baseline. Slow physiological events may still be flagged; slow ocular artifacts may be missed.']
    events=[]; unassessable=[]; channel_summaries={}

    def event(ch, lo, hi, kind, features, method, note):
        return {'recording_id':recording_id, 'channel':ch,
                'start_s':round(lo/sfreq,6),'end_s':round(hi/sfreq,6),
                'artifact_type':kind,'severity':'review',
                'feature_values':features,'detection_method':method,
                'detector_version':DETECTOR_VERSION,
                'confidence_or_review_status':'uncalibrated_candidate_requires_review',
                'threshold_configuration':asdict(cfg),
                'assessable':True,'notes':note,'window_count':1}

    for ch in eeg_channels:
        windows=[]
        suppressed_slow_dominant=0
        for starts, batch in _window_batches(raw,ch,win,hop,read):
            finite = np.all(np.isfinite(batch), axis=1)
            valid_rows = batch[finite]
            if len(valid_rows):
                f, powers = signal.periodogram(valid_rows, fs=sfreq, window='hann',
                                               detrend='linear', axis=-1)
                relevant = (f>=0.5) & (f<=30)
                high = (f>=4) & (f<=30)
                totals = np.sum(powers[:, relevant], axis=1)
                high_powers = np.sum(powers[:, high], axis=1)
                fractions = np.divide(high_powers, totals,
                                      out=np.zeros_like(totals), where=totals>0)
                band_rms_values = np.sqrt(high_powers * (f[1]-f[0])) if len(f)>1 else np.zeros(len(valid_rows))
                peak_to_peak = np.ptp(valid_rows, axis=1)
                rms_values = np.sqrt(np.mean(valid_rows**2, axis=1))
                jumps = (np.max(np.abs(np.diff(valid_rows,axis=1)),axis=1)
                         if win>1 else np.zeros(len(valid_rows)))
            good_idx=0
            for idx, a in enumerate(starts):
                a=int(a);b=a+win
                if finite[idx]:
                    windows.append((a,b,True,float(peak_to_peak[good_idx]),
                                    float(rms_values[good_idx]),float(jumps[good_idx]),
                                    float(fractions[good_idx]),float(band_rms_values[good_idx])))
                    good_idx+=1
                else:
                    windows.append((a,b,False,None,None,None,None,None))
                    events.append(event(ch,a,b,'non_finite_samples',{},'finite_window',
                                        'Non-finite values detected; EEG interval requires review.'))
        valid=[w for w in windows if w[2]]
        if len(valid)<cfg.minimum_reference_windows:
            unassessable.append({'channel':ch,'detector':'windowed_amplitude',
                                 'reason':f'Only {len(valid)} valid windows; requires {cfg.minimum_reference_windows}.'})
        else:
            baseline_rms=float(np.median([w[4] for w in valid]))
            baseline_ptp=float(np.median([w[3] for w in valid]))
            baseline_jump=float(np.median([w[5] for w in valid]))
            baseline_band_rms=float(np.median([w[7] for w in valid]))
            flat_threshold=cfg.flatline_ptp_uv*1e-6
            for a,b,_,ptp,rms,jump,high_fraction,band_rms in valid:
                # A low-voltage channel is not automatically a broken electrode.
                if ptp <= flat_threshold and baseline_ptp >= cfg.flatline_reference_ratio*flat_threshold:
                    events.append(event(ch,a,b,'possible_local_dropout',
                        {'min_peak_to_peak_uv':round(ptp*1e6,6),'reference_median_ptp_uv':round(baseline_ptp*1e6,6)},
                        'window_ptp_vs_channel_reference','Localized low variability; channel contact and legitimate quiet activity should be reviewed.'))
                if baseline_rms>0 and rms > cfg.rms_burst_ratio*baseline_rms:
                    if (high_fraction >= cfg.rms_min_4_30hz_fraction and baseline_band_rms>0
                            and band_rms > cfg.rms_band_reference_ratio * baseline_band_rms):
                        events.append(event(ch,a,b,'high_rms_burst_candidate',
                            {'max_rms_uv':round(rms*1e6,6), 'reference_median_rms_uv':round(baseline_rms*1e6,6),
                             'max_rms_ratio':round(rms/baseline_rms,6),
                             'min_4_30hz_fraction':round(high_fraction,6),
                             'max_4_30hz_rms_ratio':round(band_rms/baseline_band_rms,6)},
                            'window_rms_spectral_gate',
                            'High-amplitude 4–30 Hz rich activity; not confirmed EMG. Exclude nothing automatically.'))
                    else:
                        # Low-frequency-dominant high-amplitude EEG is ambiguous;
                        # protect candidate slow waves/K-complexes from automatic
                        # labeling. This can also miss true slow ocular/motion artifacts.
                        suppressed_slow_dominant += 1
                if jump > cfg.max_jump_uv*1e-6 and baseline_jump>0 and jump > cfg.max_jump_reference_ratio*baseline_jump:
                    events.append(event(ch,a,b,'abrupt_change_candidate',
                        {'max_sample_jump_uv':round(jump*1e6,6),
                         'reference_median_jump_uv':round(baseline_jump*1e6,6)},
                        'window_max_derivative_vs_reference',
                        'Abrupt sample-to-sample change, not definitive motion, eye blink or electrode artifact.'))

        # Spectral mains check at larger independent window scale; raw samples.
        if sfreq/2 <= cfg.mains_frequency_hz+5 or raw.n_times < line_win:
            unassessable.append({'channel':ch,'detector':'mains_spectral_prominence',
                'reason':'Mains frequency is above usable Nyquist limit or recording is too short.'})
        else:
            line_windows=[]
            for starts, batch in _window_batches(raw,ch,line_win,line_hop,max(read,line_win)):
                ratios=_line_prominences_batch(batch,sfreq,cfg.mains_frequency_hz)
                line_windows.extend((int(a),int(a)+line_win,r) for a,r in zip(starts,ratios))
            if sum(r is not None for _,_,r in line_windows) < cfg.line_min_consecutive_windows:
                unassessable.append({'channel':ch,'detector':'mains_spectral_prominence',
                    'reason':'Insufficient consecutive assessable spectral windows.'})
            else:
                # Minimum consecutive detections suppress isolated stochastic peaks.
                flags=[r is not None and r >= cfg.line_noise_prominence_ratio for _,_,r in line_windows]
                start=None
                for j in range(len(flags)+1):
                    good=j<len(flags) and flags[j]
                    if good and start is None: start=j
                    if not good and start is not None:
                        if j-start >= cfg.line_min_consecutive_windows:
                            for a,b,r in line_windows[start:j]:
                                events.append(event(ch,a,b,'possible_mains_interference',
                                    {'max_prominence_ratio':round(r,6),
                                     'mains_frequency_hz':cfg.mains_frequency_hz},
                                    'raw_hann_periodogram_mains_peak',
                                    'Unfiltered spectral peak near configured mains frequency.'))
                        start=None
        channel_summaries[ch]={'window_count':len(windows),'finite_window_count':len(valid),
                               'slow_dominant_burst_windows_not_flagged':suppressed_slow_dominant,
                               'duration_s':duration}

    events=_merge_intervals(events)
    mask={}
    for ch in eeg_channels:
        intervals=[{'start_s':e['start_s'],'end_s':e['end_s'],
                    'artifact_type':e['artifact_type']} for e in events if e['channel']==ch]
        fraction=_coverage([(e['start_s'],e['end_s']) for e in intervals],duration)
        mask[ch]=intervals
        channel_summaries[ch]['flagged_fraction']=round(fraction,6)
        channel_summaries[ch]['flagged_seconds']=round(fraction*duration,6)
        channel_summaries[ch]['review_recommended']=fraction>0
    return {'detector_version':DETECTOR_VERSION,'mode':'experimental_non_destructive',
            'status':('unassessable' if not eeg_channels else
                'partial_unassessable' if unassessable else 'complete'),
            'configuration':asdict(cfg),'eeg_channels':eeg_channels,
            'events':events,'quality_mask_intervals':mask,'channel_summary':channel_summaries,
            'unassessable':unassessable, 'notes':notes,
            'downstream_mask_applied':False,'artifact_correction_performed':False}
