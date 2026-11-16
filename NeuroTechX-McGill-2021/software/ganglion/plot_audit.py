"""Optional static figure of audit evidence (requires matplotlib).

No EEG interpretation: the frequency axis is explicitly the nominal 200 Hz
sample-index axis, even when the recorded timing does not support that rate.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch

from validation_io import load_recording


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,default=Path(__file__).resolve().parent/'validation_reports/audit/audit.json')
    parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'validation_reports/audit/evidence.png')
    args=parser.parse_args()
    payload=json.loads(args.audit.read_text())
    gui=[r for r in payload['files'] if 'OpenBCI-RAW' in r['file'] and r.get('analysis',{}).get('timing',{}).get('count',0)>1]
    lsl=[r for r in payload['files'] if r['file'].endswith('.npz')]
    if not gui or not lsl:raise SystemExit('GUI + LSL audit entries are required.')
    latest=load_recording(gui[-1]['file']);first=load_recording(lsl[0]['file'])
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(2,2,figsize=(15,9),layout='constrained')
    fig.suptitle('Existing Ganglion recordings: acquisition evidence before SSVEP interpretation',fontsize=18,fontweight='bold')
    rates=[r['analysis']['timing']['timestamp_rate_hz'] for r in gui]
    labels=[Path(r['file']).stem.replace('OpenBCI-RAW-2026-','').replace('_','\n') for r in gui]
    ax[0,0].bar(np.arange(len(gui)),rates,color=['#b0573f' if abs(v/200-1)>.05 else '#317c83' for v in rates])
    ax[0,0].axhline(200,color='#283846',linestyle='--',label='Header: 200 Hz')
    ax[0,0].set(xticks=np.arange(len(gui)),xticklabels=labels,ylabel='(N - 1) / timestamp span [Hz]',ylim=(0,230),title='A. File row rate: recent recordings around 83 Hz')
    ax[0,0].tick_params(axis='x',labelsize=6,rotation=65);ax[0,0].legend(fontsize=9)
    dt=np.diff(first['timestamps'])*1000
    ax[0,1].plot(np.arange(len(dt)),dt,color='#387787',linewidth=.8)
    bad=np.flatnonzero(dt<0);ax[0,1].scatter(bad,dt[bad],color='#b0573f',s=14,label=f'{len(bad)} backward steps')
    ax[0,1].axhline(0,color='#666',linestyle='--');ax[0,1].set(title='B. LSL timestamps reverse before CCA',xlabel='Received sample interval',ylabel='Timestamp difference [ms]');ax[0,1].legend(fontsize=9)
    x=latest['samples'][-400:]
    for ch in range(4):ax[1,0].plot(np.arange(len(x)),x[:,ch],linewidth=.7,label=f'CH{ch+1}',alpha=.8)
    for rail in [-15500,15500]:ax[1,0].axhline(rail,color='#b0573f',linestyle=':',linewidth=1)
    ax[1,0].set(title='C. Raw values near input range in latest GUI file',xlabel='Sample index (time axis not verified)',ylabel='GUI raw EXG [uV]');ax[1,0].legend(ncol=4,fontsize=8)
    f,p=welch(first['samples'],fs=200,nperseg=800,axis=0)
    for ch in range(4):ax[1,1].plot(f,10*np.log10(np.maximum(p[:,ch],1e-30)),label=f'CH{ch+1}')
    ax[1,1].axvspan(8,13,alpha=.08,color='green')
    ax[1,1].set(xlim=(1,90),title='D. Spectrum is provisional when timing fails',xlabel='Frequency assuming 200 Hz [NOT verified Hz]',ylabel='PSD [dB uV^2/Hz]');ax[1,1].legend(ncol=4,fontsize=8)
    fig.supxlabel('A/C: GUI files through Nov 8, 2026. B/D: first saved SSVEP NPZ (Oct 3 KST). Conditions and electrode contact unknown.\nThese observations identify commissioning checks; they do not diagnose hardware or establish neural EEG.',fontsize=10)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.out,dpi=160)
    print(args.out.resolve())


if __name__=='__main__':main()
