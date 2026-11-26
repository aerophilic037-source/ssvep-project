"""Persisted calibration/evaluation state machine for the native workstation."""
import html
import json
import secrets
import re
from pathlib import Path
import numpy as np
from flask import request, jsonify
from personal_models import CONFIG, train, predict, fingerprint


def plan(seed):
    rng=np.random.default_rng(seed);result=[]
    for group in range(15):
        for f in rng.permutation([12.,15.,0.]):
            result.append({'slot':len(result),'group':group,'condition':'choice' if f else 'no_control',
                'frequency':float(f) if f else None,'duration':6,'candidates':[12.,15.],
                'cue':f'{f:g} Hz 표시를 바라보세요.' if f else '눈은 뜨고 화면 옆의 정지된 물체를 보세요.'})
    return result


def accepted_slots(session,phase):
    return {t['personal']['slot'] for t in session['trials'] if t.get('personal',{}).get('phase')==phase and
            (phase=='evaluation' or t.get('personal',{}).get('eligible',False))}


def pending(session,phase):
    used=accepted_slots(session,phase)
    return [dict(b,personal_phase=phase,personal_slot=b['slot']) for b in session['personal'][phase+'_plan'] if b['slot'] not in used]


def validate_start(session,body):
    exp=session.get('personal')
    if not exp:
        if 'personal_phase'in body:raise ValueError('개인 실험을 먼저 준비하세요.')
        return None
    phase=body.get('personal_phase')
    expected='evaluation' if exp.get('model_id') else 'calibration'
    if phase!=expected:raise ValueError('현재 개인 실험 단계와 다릅니다. 별도 일반 실험은 새 세션을 만드세요.')
    todo=pending(session,phase)
    if not todo:raise ValueError('이 단계의 기록이 완료되었습니다.')
    b=todo[0]
    if body.get('personal_slot')!=b['slot'] or any(body.get(k)!=b[k] for k in ('condition','frequency','duration','candidates')):
        raise ValueError('서버가 지정한 다음 시행과 일치하지 않습니다.')
    return {'phase':phase,'slot':b['slot'],'group':b['group'],'model_id':exp.get('model_id')}


def aligned_epoch(samples,timestamps,trial):
    marker=trial.get('onset');x=np.asarray(samples);ts=np.asarray(timestamps)
    if not marker:raise ValueError('첫 자극 프레임 시작 마커가 없습니다.')
    if marker['uncertainty_ms']>10:raise ValueError('브라우저 시계 추정 오차가 10 ms를 넘었습니다.')
    if len(x)<1000 or not np.isfinite(x).all() or not np.isfinite(ts).all() or np.any(np.diff(ts)<0):
        raise ValueError('유한한 연속 EEG 5초 이상과 순방향 시각이 필요합니다.')
    # BLE delivery is bursty. Fit a uniform sample clock, retain the raw clock
    # and explicitly quantify residuals. This cannot validate ADC/optical timing.
    idx=np.arange(len(ts));slope,offset=np.polyfit(idx,ts-ts[0],1)
    rate=1/slope;rms=float(np.sqrt(np.mean((ts-ts[0]-(offset+slope*idx))**2)))
    if not 196<=rate<=204 or rms>.025 or np.max(np.diff(ts))>.15:
        raise ValueError(f'시계 재구성 기준 미통과: {rate:.2f} Hz, 잔차 {rms*1000:.1f} ms')
    fitted=ts[0]+offset+slope*idx
    grid=marker['server_time']+CONFIG['settle']+np.arange(800)/200
    if grid[0]<fitted[0] or grid[-1]>fitted[-1]:raise ValueError('자극 시작 후 1~5초 EEG가 부족합니다.')
    epoch=np.column_stack([np.interp(grid,fitted,x[:,c]) for c in range(x.shape[1])])
    diagnostic={'estimated_rate_hz':float(rate),'fit_rms_ms':rms*1000,'clock_uncertainty_ms':marker['uncertainty_ms'],
        'onset_delay_from_capture_ms':(marker['server_time']-trial['start_lsl'])*1000,
        'physical_onset_verified':False,'method':CONFIG['alignment']}
    return epoch,diagnostic


def complete(session,trial,samples,ts,folder):
    if not trial.get('personal'):return
    p=trial['personal'];p['eligible']=False
    try:
        if not trial['valid_for_decision']:raise ValueError('신호/화면 품질 미통과 또는 중단 기록')
        epoch,diag=aligned_epoch(samples,ts,trial)
        p.update(eligible=True,alignment=diag)
        if p['phase']=='evaluation':
            model=json.loads((folder/'personal_model.json').read_text())
            if model['id']!=fingerprint(model) or model['id']!=p['model_id'] or model['config']!=CONFIG:
                raise ValueError('고정 모델의 해시가 일치하지 않습니다.')
            p['results']=predict(model,epoch[:,session['setup']['channels']])
    except (ValueError,OSError) as exc:
        p.update(eligible=False,error=str(exc))


def summary(session):
    exp=session.get('personal')
    if not exp:return None
    result={'calibration_completed':len(accepted_slots(session,'calibration')),
            'evaluation_completed':len(accepted_slots(session,'evaluation')),
            'model_id':exp.get('model_id'),'cv':exp.get('cv'), 'algorithms':{}}
    rows=[t for t in session['trials'] if t.get('personal',{}).get('phase')=='evaluation']
    for name in ['etrca','ecca']:
        targets=[t for t in rows if t['frequency'] is not None];controls=[t for t in rows if t['frequency'] is None]
        def get(t,k):return t['personal'].get('results',{}).get(name,{}).get(k)
        correct=sum(get(t,'prediction')==t['frequency'] for t in targets)
        accepted=sum(get(t,'prediction')is not None for t in targets)
        forced=sum(get(t,'top1')==t['frequency'] for t in targets)
        valid_controls=[t for t in controls if t['personal'].get('eligible')]
        result['algorithms'][name]={'target_attempts':len(targets),'correct':correct,'accepted':accepted,
            'accuracy_all':correct/len(targets) if targets else None,
            'accuracy_accepted':correct/accepted if accepted else None,'forced_top1_correct':forced,
            'rejected':len(targets)-accepted,'wrong_accepted':accepted-correct,
            'invalid_targets':sum(not t['personal'].get('eligible') for t in targets),
            'control_attempts':len(controls),'valid_controls':len(valid_controls),
            'control_false_positives':sum(get(t,'prediction')is not None for t in valid_controls),
            'invalid_controls':len(controls)-len(valid_controls),
            'per_target':{str(f):{'attempts':sum(t['frequency']==f for t in targets),'correct':sum(t['frequency']==f and get(t,'prediction')==f for t in targets)} for f in CONFIG['targets']}}
    return result


def write_personal_report(session,folder):
    if not session.get('personal'):return
    report={'summary':summary(session),'experiment':session['personal'],
            'trials':[{'id':t['id'],'target':t['frequency'],**t['personal']} for t in session['trials'] if t.get('personal')]}
    raw=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)
    for name,text in [('personal_results.json',raw),('personal_report.html',
        '<!doctype html><meta charset="utf-8"><title>개인 SSVEP 결과</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}pre{white-space:pre-wrap}</style><h1>개인 SSVEP · 보정 / 독립 평가</h1><p>소프트웨어 시간 정렬만 확인합니다. 광출력·ADC 동기화는 미검증입니다. 보정 CV와 독립 평가를 구분하세요. 무효 평가도 재시도 없이 분모에 남깁니다.</p><pre>'+html.escape(raw)+'</pre>')]:
        tmp=folder/(name+'.tmp');tmp.write_text(text);tmp.replace(folder/name)


def register(app,state,lock,folder,now,persist,native):
    def session():
        if not native or not state['session']:raise ValueError('Native 새 세션이 필요합니다.')
        if state['trial']:raise ValueError('진행 중인 시행을 먼저 마치세요.')
        return state['session']

    @app.get('/api/personal/clock')
    def clock_sync():return jsonify(server_time=now())

    @app.post('/api/personal/onset')
    def onset():
        with lock:
            b=request.get_json();t=state['trial'];stamp=b.get('server_time');uncertainty=b.get('uncertainty_ms')
            if not t or t['id']!=b.get('id') or not t.get('personal'):raise ValueError('시행 ID 오류')
            if t.get('onset'):raise ValueError('시작 마커는 한 번만 기록할 수 있습니다.')
            if any(type(v)not in (float,int) or not np.isfinite(v) for v in (stamp,uncertainty)) or not 0<=uncertainty<=10:
                raise ValueError('시계 오차/시각 오류')
            if not t['start_lsl']-.02<=stamp<=now()+.02 or now()-stamp>.5:raise ValueError('시작 마커 수신 지연/범위 오류')
            geometry=b.get('geometry')
            if not isinstance(geometry,dict) or any(type(geometry.get(k))not in (int,float) or not np.isfinite(geometry[k]) or geometry[k]<=0 for k in ['width','height','dpr','target_px']):
                raise ValueError('화면 크기 기록이 없습니다.')
            exp=state['session']['personal']
            if exp.get('geometry') and exp['geometry']!=geometry:
                raise ValueError('화면 크기/배율이 바뀌었습니다. 원래 조건으로 복원하거나 새 세션을 만드세요.')
            exp['geometry']=geometry
            t['onset']={'geometry':geometry,'server_time':stamp,'received_time':now(),'uncertainty_ms':uncertainty,'physical_onset_verified':False}
            return jsonify(ok=True)

    @app.post('/api/personal/prepare')
    def prepare():
        with lock:
            s=session()
            if s['trials'] or s.get('personal'):raise ValueError('빈 새 세션에서 시작하세요.')
            env=request.get_json().get('environment',{})
            for key in ['distance_cm','target_cm']:
                if type(env.get(key))not in (int,float) or not np.isfinite(env[key]) or not 1<=env[key]<=200:
                    raise ValueError('실제 시청 거리와 자극 한 변(cm)을 입력하세요.')
            if not s['setup'].get('reference','').strip() or not s['setup'].get('ground','').strip():
                raise ValueError('실제 REF와 D_G 위치를 입력하고 새 세션을 만드세요.')
            seed=secrets.randbits(32)
            s['personal']={'version':1,'seed':seed,'environment':env,'config':CONFIG,
                'calibration_plan':plan(seed),'evaluation_plan':plan(seed+1),'model_id':None}
            persist();return jsonify(summary(s))

    @app.get('/api/personal/status')
    def personal_status():
        with lock:return jsonify(summary(state['session']) if state['session'] else None)

    @app.get('/api/personal/plan/<phase>')
    def get_plan(phase):
        with lock:
            s=session()
            if not s.get('personal') or phase not in ['calibration','evaluation']:raise ValueError('개인 실험 단계 오류')
            if (phase=='evaluation')!=bool(s['personal'].get('model_id')):raise ValueError('보정 완료 후 모델 고정이 필요합니다.')
            return jsonify(blocks=pending(s,phase),phase=phase)

    @app.post('/api/personal/train')
    def train_model():
        with lock:
            s=session();exp=s.get('personal')
            if not exp or exp.get('model_id'):raise ValueError('이미 고정된 모델은 재학습할 수 없습니다. 새 세션을 만드세요.')
            if len(accepted_slots(s,'calibration'))!=45:raise ValueError('유효한 보정 45회를 먼저 완료하세요.')
            dest=folder/s['id'];epochs=[];labels=[];groups=[];ids=[]
            for t in s['trials']:
                p=t.get('personal',{})
                if p.get('phase')!='calibration' or not p.get('eligible'):continue
                with np.load(dest/t['recording'],allow_pickle=False) as z:
                    epoch,_=aligned_epoch(z['samples'],z['timestamps'],t)
                epochs.append(epoch[:,s['setup']['channels']]);labels.append(t['frequency'] or 0);groups.append(p['group']);ids.append(t['id'])
            model=train(epochs,labels,groups,ids)
            tmp=dest/'personal_model.tmp';tmp.write_text(json.dumps(model,allow_nan=False));tmp.replace(dest/'personal_model.json')
            exp.update(model_id=model['id'],cv=model['cv'],gates=model['gates'],training_ids=ids)
            persist();return jsonify(summary(s))

    @app.post('/api/personal/resume')
    def resume():
        with lock:
            if state['trial']:raise ValueError('진행 중인 시행을 먼저 마치세요.')
            ident=request.get_json().get('id','')
            if not re.fullmatch(r'\d{8}T\d{6}Z_[a-f0-9]{12}',ident):raise ValueError('세션 ID 오류')
            path=folder/ident/'session.json'
            if not path.exists():raise ValueError('저장된 세션을 찾지 못했습니다.')
            s=json.loads(path.read_text())
            if not s.get('personal'):raise ValueError('개인 실험 세션이 아닙니다.')
            if s['personal']['config']!=CONFIG:raise ValueError('학습 설정 버전이 다릅니다. 새 세션을 만드세요.')
            if s['personal'].get('model_id'):
                model=json.loads((folder/ident/'personal_model.json').read_text())
                if model['id']!=fingerprint(model) or model['id']!=s['personal']['model_id'] or model['config']!=CONFIG:raise ValueError('모델 무결성 오류')
            state['session']=s;return jsonify(id=ident,status=summary(s))
