"""Personal SSVEP: filter-bank regularized ensemble TRCA and four-term eCCA.

All fitting and rejection calibration use calibration trials only. A trial is
one indivisible CV group. Default: 3 Chebyshev subbands, 4 s, 200 Hz, Q30 notch.
References: Nakanishi 2018 TRCA (doi:10.1109/TBME.2017.2694818),
Nakanishi 2015 individual CCA (doi:10.1371/journal.pone.0140703).
eCCA feature definition is explicit below; no hidden phase/lag optimization.
"""
import hashlib
import json
import numpy as np
from scipy.linalg import eigh
from scipy.signal import iirnotch, filtfilt, cheb1ord, cheby1, sosfiltfilt

CONFIG={'version':1,'fs':200,'seconds':4,'settle':1,'bands':[6,14,22],
        'stop_low':[4,10,16],'high':90,'stop_high':95,'harmonics':5,
        'ridge':1e-6,'notch':60,'targets':[12.,15.],
        'alignment':'linear fit of producer monotonic timestamps to sample index; resample to onset+1..5s; software onset only'}


def corr(x,y):
    x=np.asarray(x).ravel();y=np.asarray(y).ravel()
    x=x-x.mean();y=y-y.mean();den=np.linalg.norm(x)*np.linalg.norm(y)
    return float(np.clip(x@y/den,-1,1)) if den>1e-12 else 0.


def cca_weights(x,y):
    x=x-x.mean(0);y=y-y.mean(0)
    def ortho(a):
        u,s,v=np.linalg.svd(a,full_matrices=False)
        keep=s>max(s[0]*1e-8,1e-12)
        return u[:,keep],v[keep].T/s[keep]
    qx,px=ortho(x);qy,py=ortho(y)
    if not qx.shape[1] or not qy.shape[1]:
        return np.zeros(x.shape[1]),np.zeros(y.shape[1])
    u,_,vh=np.linalg.svd(qx.T@qy,full_matrices=False)
    return px@u[:,0],py@vh.T[:,0]


def references(f,n):
    t=(np.arange(n)/CONFIG['fs'])+CONFIG['settle']
    return np.column_stack([fn(2*np.pi*f*h*t) for h in range(1,6) for fn in (np.sin,np.cos)])


def preprocess(epoch):
    x=np.asarray(epoch,float)
    if x.ndim!=2 or x.shape[0]!=800 or not 1<=x.shape[1]<=4 or not np.isfinite(x).all():
        raise ValueError('개인 학습에는 유한한 4초 × 선택 채널 EEG가 필요합니다.')
    b,a=iirnotch(60,30,fs=200);x=filtfilt(b,a,x,axis=0)
    out=[]
    for low,stop in zip(CONFIG['bands'],CONFIG['stop_low']):
        n,wn=cheb1ord([low,90],[stop,95],3,40,fs=200)
        out.append(sosfiltfilt(cheby1(n,.5,wn,btype='bandpass',fs=200,output='sos'),x,axis=0))
    return np.asarray(out)


def fit(bands,labels):
    """bands: trial × band × sample × channel; no-control excluded from fit."""
    bands=np.asarray(bands);labels=np.asarray(labels)
    templates=[];weights=[]
    for target in CONFIG['targets']:
        trials=bands[labels==target]
        if len(trials)<2:raise ValueError('각 목표에 최소 2개의 독립 학습 시행이 필요합니다.')
        template=trials.mean(0);templates.append(template)
        ws=[]
        for b in range(len(CONFIG['bands'])):
            x=trials[:,b]-trials[:,b].mean(axis=1,keepdims=True)
            q=np.einsum('itc,itd->cd',x,x)
            total=x.sum(0);s=total.T@total-q
            scale=max(np.trace(q)/q.shape[0],1e-12)
            _,v=eigh((s+s.T)/2,(q+q.T)/2+np.eye(q.shape[0])*scale*CONFIG['ridge'])
            w=v[:,-1];ws.append(w/np.linalg.norm(w))
        weights.append(ws)
    return {'templates':np.asarray(templates).tolist(),'weights':np.asarray(weights).tolist()}


def scores(model,band):
    templates=np.asarray(model['templates']);ws=np.asarray(model['weights'])
    result={'etrca':np.zeros(2),'ecca':np.zeros(2)}
    for b,x in enumerate(band):
        ensemble=ws[:,b].T
        weight=(b+1)**-1.25+.25
        for k,f in enumerate(CONFIG['targets']):
            template=templates[k,b];y=references(f,len(x))
            r=corr(x@ensemble,template@ensemble)
            result['etrca'][k]+=weight*np.sign(r)*r*r
            wx,wy=cca_weights(x,y);wt,_=cca_weights(template,y);wxt,_=cca_weights(x,template)
            # Four signed correlation features: X/Y, X/template with joint
            # X-template weights, X/template with X-Y and template-Y weights.
            rs=[corr(x@wx,y@wy),corr(x@wxt,template@wxt),
                corr(x@wx,template@wx),corr(x@wt,template@wt)]
            result['ecca'][k]+=weight*sum(np.sign(v)*v*v for v in rs)
    return {key:value.tolist() for key,value in result.items()}


def decision(values,gate):
    order=np.argsort(values)[::-1];best=float(values[order[0]]);margin=best-float(values[order[1]])
    top=CONFIG['targets'][order[0]] if margin>1e-12 else None
    return {'scores':values,'top1':top,'prediction':top if top is not None and best>gate['score'] and margin>gate['margin'] else None}


def calibrate_gate(predictions,labels):
    """OOF-only grid; empirical control FPR <= 1/15, prefer fewer wrong accepts.
    Performance on this same grid is calibration-fit, not unbiased test accuracy.
    """
    a=np.asarray(predictions);labels=np.asarray(labels);targets=labels!=0;controls=~targets
    best=a.max(1);margin=np.abs(a[:,0]-a[:,1]);top=np.array(CONFIG['targets'])[a.argmax(1)]
    candidates_s=np.unique(np.r_[-1e6,best,1e6]);candidates_m=np.unique(np.r_[0,margin])
    winner=None
    for s in candidates_s:
        for m in candidates_m:
            accepted=(best>s)&(margin>m)
            fp=int(np.sum(accepted&controls))
            if fp>1:continue
            correct=int(np.sum(accepted&targets&(top==labels)))
            wrong=int(np.sum(accepted&targets&(top!=labels)))
            key=(correct-wrong,-fp,-wrong,correct)
            if winner is None or key>winner[0]:winner=(key,{'score':float(s),'margin':float(m)})
    return winner[1]


def train(epochs,labels,groups,trial_ids):
    labels=np.asarray(labels);groups=np.asarray(groups)
    if any(np.sum(labels==f)!=15 for f in [0,12,15]) or set(groups)!=set(range(15)):
        raise ValueError('각 목표/시선 이탈 15회와 완전한 15개 블록이 필요합니다.')
    if len(set(trial_ids))!=45 or any(sorted(labels[groups==g])!=[0,12,15] for g in range(15)):
        raise ValueError('보정 블록 또는 기록 중복 오류입니다.')
    bands=np.asarray([preprocess(x) for x in epochs]);oof={a:[None]*45 for a in ['etrca','ecca']}
    for g in range(15):
        use=groups!=g;model=fit(bands[use],labels[use])
        for i in np.where(~use)[0]:
            for name,v in scores(model,bands[i]).items():oof[name][i]=v
    gates={name:calibrate_gate(v,labels) for name,v in oof.items()}
    cv={name:{'forced_choice_correct':sum(int(np.argmax(v)==CONFIG['targets'].index(float(y))) for v,y in zip(values,labels) if y),
              'target_trials':30,'gate_fit_is_not_test':True} for name,values in oof.items()}
    curves={name:[] for name in oof}
    for count in (3,5,10,14):
        hits={name:0 for name in oof}
        if count==14:
            hits={name:cv[name]['forced_choice_correct'] for name in oof}
        else:
            for g in range(15):
                available=np.array([v for v in range(15) if v!=g])
                selected=np.random.default_rng(20261126+g).permutation(available)[:count]
                small=fit(bands[np.isin(groups,selected)],labels[np.isin(groups,selected)])
                for i in np.where((groups==g)&(labels!=0))[0]:
                    for name,v in scores(small,bands[i]).items():
                        hits[name]+=int(CONFIG['targets'][np.argmax(v)]==labels[i])
        for name in oof:curves[name].append({'training_trials_per_target':count,'correct':hits[name],'n':30})
    for name in cv:cv[name]['learning_curve']=curves[name]
    model=fit(bands,labels)
    model.update(config=CONFIG,calibration_trial_ids=trial_ids,gates=gates,cv=cv,
                 oof=[{'trial_id':tid,'label':int(label),'group':int(group),'scores':{name:oof[name][i] for name in oof}}
                      for i,(tid,label,group) in enumerate(zip(trial_ids,labels,groups))])
    model['id']=fingerprint(model)
    return model


def fingerprint(model):
    return hashlib.sha256(json.dumps({k:v for k,v in model.items() if k!='id'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def predict(model,epoch):
    return {a:decision(v,model['gates'][a]) for a,v in scores(model,preprocess(epoch)).items()}
