"""Offline FBCCA (Chen 2015 M3-style), adapted to 200 Hz Ganglion.

Five overlapping Chebyshev-I bands, lower pass edges 6/14/22/30/38 Hz,
upper pass 90 Hz, upper stop 95 Hz (original 100 Hz is Nyquist at 200 Hz).
Five sine/cosine harmonics; sum((m**-1.25 + .25) * rho_m**2).
Scores are not probabilities and must not use standard CCA rejection thresholds.
Filter design reference: github.com/mnakanishi/TRCA-SSVEP/src/filterbank.m
"""
import numpy as np
from scipy.signal import cheb1ord, cheby1, sosfiltfilt
from decoder import basis

CONFIG = dict(pass_low=[6,14,22,30,38], stop_low=[4,10,16,24,32],
              pass_high=90, stop_high=95, harmonics=5, weight_a=1.25, weight_b=.25,
              order_ripple_db=3, design_ripple_db=.5, stop_attenuation_db=40)


def fbcca_scores(samples, fs, targets):
    x=np.asarray(samples,dtype=float)
    f=np.asarray(targets,dtype=float)
    if x.ndim!=2 or x.shape[1]<1 or not np.isfinite(x).all():
        raise ValueError('Finite samples × channels matrix required')
    if not np.isfinite(fs) or fs/2<=CONFIG['stop_high'] or len(x)<2*fs:
        raise ValueError('Need >=2 seconds and Nyquist >95 Hz')
    if f.ndim!=1 or not 1<=len(f)<=20 or not np.isfinite(f).all() or len(np.unique(f))!=len(f) or np.any((f<8)|(f>17.5)):
        raise ValueError('Need 1–20 unique targets in 8–17.5 Hz')
    t=np.arange(len(x))/fs
    refs=[basis(np.column_stack([wave(2*np.pi*freq*h*t)
          for h in range(1,CONFIG['harmonics']+1) for wave in (np.sin,np.cos)])) for freq in f]
    bands=[]
    for low,stop in zip(CONFIG['pass_low'],CONFIG['stop_low']):
        n,wn=cheb1ord([low,CONFIG['pass_high']],[stop,CONFIG['stop_high']],3,40,fs=fs)
        sos=cheby1(n,.5,wn,btype='bandpass',fs=fs,output='sos')
        q=basis(sosfiltfilt(sos,x,axis=0))
        row=[]
        for ref in refs:
            sv=np.linalg.svd(q.T@ref,compute_uv=False)
            row.append(float(np.clip(sv[0],0,1)) if len(sv) else 0.)
        bands.append(row)
    weights=np.arange(1,len(bands)+1,dtype=float)**-1.25+.25
    total=weights@np.square(bands)
    return {'scores':{str(float(freq)):float(score) for freq,score in zip(f,total)},
            'band_correlations':bands, 'weights':weights.tolist()}
