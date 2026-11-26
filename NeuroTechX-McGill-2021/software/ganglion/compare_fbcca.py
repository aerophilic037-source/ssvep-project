"""Reproducible read-only replay of native recordings; writes separate reports."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import numpy as np
from scipy.signal import iirnotch, filtfilt
from scipy.stats import binomtest
from validation import cca_scores
from fbcca import fbcca_scores, CONFIG


def winner(scores):
    ordered=sorted(scores,key=scores.get,reverse=True)
    if len(ordered)<2 or scores[ordered[0]]-scores[ordered[1]]<1e-12:
        return None
    return float(ordered[0])


def replay(folder):
    session=json.loads((folder/'session.json').read_text())
    paths={}
    for p in sorted(folder.glob('*.npz')):
        with np.load(p,allow_pickle=False) as z:
            meta=json.loads(str(z['metadata']))
        paths[meta['id']]=p
    rows=[]
    for i,trial in enumerate(session['trials'],1):
        if trial['condition'] not in ('choice','single','baseline','no_control'):continue
        p=paths[trial['id']]
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        with np.load(p,allow_pickle=False) as z:
            meta=json.loads(str(z['metadata']))
            mask=z['arrival_timestamps']>=meta['start_lsl']+meta.get('settle_seconds',1.)
            channels=meta.get('setup',session['setup'])['channels']
            x=z['samples'][mask][:,channels].copy()
        candidates=meta['candidates'];fs=meta['stream']['sampling_rate']
        row={'session':folder.name,'trial':i,'condition':meta['condition'],'target':meta['frequency'],
             'candidates':candidates,'valid':meta['valid_for_decision'],'aborted':meta['aborted'],
             'original_prediction':meta.get('prediction'),'file':str(p.resolve()),'sha256':digest,
             'sample_count':len(x),'fs':fs,'channels':channels}
        if meta['aborted'] or len(x)<fs*2 or not np.isfinite(x).all():
            row['excluded_reason']='aborted / insufficient / nonfinite'
        else:
            # Identical 60 Hz preprocessing for both algorithms. Quality flags
            # stay as originally recorded; do not retrospectively promote trials.
            b,a=iirnotch(60,30,fs=fs);x=filtfilt(b,a,x,axis=0)
            cca=cca_scores(x,fs,candidates);fb=fbcca_scores(x,fs,candidates)
            row.update(cca_scores=cca,fbcca_scores=fb['scores'],fbcca_bands=fb['band_correlations'],
                       cca_top1=winner(cca),fbcca_top1=winner(fb['scores']))
            stored=meta.get('analysis',{}).get('cca_scores_exploratory',{})
            stored={str(float(k)):v for k,v in stored.items()}
            row['cca_replay_max_difference']=max((abs(v-stored[str(float(k))]) for k,v in cca.items()),default=0)
        assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
        rows.append(row)
    return rows


def summarize(rows):
    summary=[]
    for session in dict.fromkeys(r['session'] for r in rows):
        for condition in ('choice','single'):
            all_rows=[r for r in rows if r['session']==session and r['condition']==condition and not r['aborted']]
            if not all_rows:continue
            valid=[r for r in all_rows if r['valid'] and 'cca_top1'in r]
            result={'session':session,'condition':condition,'completed':len(all_rows),'eligible':len(valid),
                    'original_accepted':sum(r['original_prediction'] is not None for r in all_rows),
                    'original_correct':sum(r['original_prediction']==r['target'] for r in all_rows)}
            for alg in ('cca','fbcca'):
                k=sum(r[alg+'_top1']==r['target'] for r in valid);n=len(valid)
                ci=binomtest(k,n).proportion_ci(method='wilson') if n else None
                result[alg]={'correct':k,'n':n,'accuracy':k/n if n else None,
                             'wilson95':list(ci) if ci else None,
                             'predictions':{str(f):sum(r[alg+'_top1']==f for r in valid) for f in sorted({v for r in valid for v in r['candidates']})}}
            better=sum(r['fbcca_top1']==r['target'] and r['cca_top1']!=r['target'] for r in valid)
            worse=sum(r['cca_top1']==r['target'] and r['fbcca_top1']!=r['target'] for r in valid)
            result['per_target']={str(f):{'n':sum(r['target']==f for r in valid), **{alg:sum(r['target']==f and r[alg+'_top1']==f for r in valid) for alg in ('cca','fbcca')}} for f in sorted({r['target'] for r in valid})}
            result['paired_discordant']={'fbcca_only_correct':better,'cca_only_correct':worse,
                'exact_two_sided_p':binomtest(better,better+worse,.5).pvalue if better+worse else 1.}
            summary.append(result)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions',nargs='+',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    roots=[p.resolve() for p in args.sessions];out=args.out.resolve()
    if any(out==p or p in out.parents for p in roots):raise ValueError('Output must be outside input sessions')
    rows=[r for folder in roots for r in replay(folder)]
    result={'config':CONFIG,'preprocessing':'same epoch: recorded 1s settling removal, nominal fs, selected channels, 60Hz notch Q30 for both',
            'limitations':['Exploratory retrospective comparison; fixed configuration, no label-driven tuning.',
                'Top-1 forced choice is not thresholded online accuracy. FBCCA rejection threshold is not calibrated.',
                'Single-target trials cannot establish multi-class accuracy; aborted/invalid trials excluded from eligible metrics.',
                'No-control has no target; forced-choice always emits a class except ties and is not an intentional-control detector.',
                'Original quality and display flags retained. No resampling or timestamp repair.'],
            'summary':summarize(rows),'trials':rows,
            'sources':['https://pubmed.ncbi.nlm.nih.gov/26035476/', 'https://github.com/mnakanishi/TRCA-SSVEP/blob/master/src/filterbank.m'],
            'no_control':{alg:{'n':sum(r['condition']=='no_control' and not r['aborted'] for r in rows),
                 'forced_outputs':sum(r['condition']=='no_control' and r.get(alg+'_top1') is not None for r in rows)} for alg in ('cca','fbcca')}}
    out.mkdir(parents=True,exist_ok=True)
    (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    fields=['session','trial','condition','target','valid','aborted','original_prediction','cca_top1','fbcca_top1','cca_scores','fbcca_scores']
    with (out/'trials.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    esc=lambda v:html.escape(str(v))
    body=''.join('<tr>'+''.join('<td>'+esc(r.get(k,''))+'</td>' for k in fields)+'</tr>' for r in rows)
    report='<!doctype html><meta charset="utf-8"><title>CCA / FBCCA offline comparison</title><style>body{font:15px system-ui;margin:30px}td,th{border:1px solid #ccc;padding:8px}table{border-collapse:collapse}pre{white-space:pre-wrap}</style><h1>CCA / FBCCA · 녹화본 재분석</h1><p>강제 선택 비교입니다. FBCCA 점수는 확률이 아니며 실시간 보류 기준은 미보정입니다. 단일 자극 적중률은 다중 선택 정확도가 아닙니다.</p><pre>'+esc(json.dumps(result['summary'],ensure_ascii=False,indent=2))+'</pre><table><tr>'+''.join('<th>'+esc(k)+'</th>' for k in fields)+'</tr>'+body+'</table><pre>'+esc(json.dumps({k:v for k,v in result.items() if k not in ('trials','summary')},ensure_ascii=False,indent=2))+'</pre>'
    (out/'index.html').write_text(report)
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2));print(out/'index.html')

if __name__=='__main__':main()
