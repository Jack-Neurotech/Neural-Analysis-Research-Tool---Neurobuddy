#!/usr/bin/env python3
"""Reproducible wall-clock A/B benchmark and report equivalence check.

Examples:
  python benchmarks/benchmark_runtime.py --optimized .
  python benchmarks/benchmark_runtime.py --baseline ../Neurobuddy_v0.7.0_Artifact_Research --optimized .

Benchmarks process() inside a fresh subprocess, excluding interpreter startup
and import time, but including initial schema validation within process().
All file products are written to a fresh temporary directory.  These are
engineering timings, NOT clinical or detection-accuracy benchmarks.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap

import mne
import numpy as np

RUNNER = '''
import json,time,sys
from pathlib import Path
from neurobuddy_v2.pipeline import process
src,out,large=sys.argv[1:4]
t=time.perf_counter()
result=process(Path(src),Path(out),artifact_mode='experimental',
               large_threshold_mb=int(large),chunk_seconds=30,player_frames=1500)
print('TIMING_JSON:'+json.dumps({'elapsed_s':time.perf_counter()-t,
                                'status':result[0][0]['processing_status']}))
'''


def make_recording(path:Path, seconds:int, channels:int, sf:int):
    rng=np.random.default_rng(223)
    time=np.arange(seconds*sf)/sf
    waves=np.asarray([12e-6*np.sin(2*np.pi*(8+i%12)*time) +
                      rng.normal(0,1.5e-6,len(time)) for i in range(channels)])
    if seconds>30:
        waves[0,20*sf:22*sf]=0
    names=[f'E{i:03d}' for i in range(channels)]
    raw=mne.io.RawArray(waves,mne.create_info(names,sf,['eeg']*channels),verbose='ERROR')
    raw.save(path,overwrite=True,verbose='ERROR')


def run(project:Path, source:Path, out:Path, limit:int):
    env=os.environ.copy()
    env.update(PYTHONPATH=str(project.resolve()), OPENBLAS_NUM_THREADS='1', MPLBACKEND='Agg')
    proc=subprocess.run([sys.executable,'-c',RUNNER,str(source),str(out),str(limit)],
                        cwd=project,env=env,capture_output=True,text=True)
    if proc.returncode:
        raise RuntimeError(f'Pipeline failed in {project}:\n{proc.stdout}\n{proc.stderr}')
    times=[x.split('TIMING_JSON:',1)[1] for x in proc.stdout.splitlines() if 'TIMING_JSON:' in x]
    if not times:
        raise RuntimeError(f'No timing obtained for {project}: {proc.stdout}')
    return json.loads(times[-1])


def normalize(report_path:Path):
    doc=json.loads(report_path.read_text(encoding='utf8'))
    # Time is the only field expected to change between equivalent runs.
    doc.get('provenance',{}).pop('created_utc',None)
    return doc


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--baseline',type=Path,help='Unmodified v0.7.0 source directory')
    p.add_argument('--optimized',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--seconds',type=int,default=120)
    p.add_argument('--channels',type=int,default=8)
    p.add_argument('--sampling-rate',type=int,default=256)
    p.add_argument('--streaming',action='store_true')
    args=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='nb-speed-bench-') as tmp:
        temp=Path(tmp)
        source=temp/'sub-001_task-rest_eeg.fif'
        make_recording(source,args.seconds,args.channels,args.sampling_rate)
        limit=0 if args.streaming else 256
        if args.baseline:
            baseline=run(args.baseline.resolve(),source,temp/'baseline',limit)
            print('Baseline:',json.dumps(baseline))
        candidate=run(args.optimized.resolve(),source,temp/'optimized',limit)
        print('Optimized:',json.dumps(candidate))
        if args.baseline:
            same=normalize(temp/'baseline'/'report.json')==normalize(temp/'optimized'/'report.json')
            print('Report equality (excluding creation time):',same)
            print('Speedup:',round(baseline['elapsed_s']/candidate['elapsed_s'],2),'x')
            if not same:
                sys.exit('ERROR: Report output differs')
    return 0

if __name__=='__main__':
    sys.exit(main())
