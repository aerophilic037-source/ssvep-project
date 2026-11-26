import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from personal_models import fit,preprocess,predict,train,fingerprint,CONFIG
from personal_experiment import plan,aligned_epoch,validate_start,pending,summary
from validation_app import create_app
from test_validation import DiagnosticReceiver


def epoch(f,seed):
    rng=np.random.default_rng(seed);t=(np.arange(800)/200)+1
    x=rng.normal(0,.3,(800,4))
    if f:
        x+=np.sin(2*np.pi*f*t+.2)[:,None]*[2,1,.6,1.5]
        x+=np.sin(2*np.pi*f*2*t+.1)[:,None]*[1,.5,.3,.8]
    return x


class PersonalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels=[f for g in range(15) for f in [12,15,0]]
        cls.groups=[g for g in range(15) for f in [12,15,0]]
        cls.model=train([epoch(f,i) for i,f in enumerate(cls.labels)],cls.labels,cls.groups,[str(i) for i in range(45)])

    def test_independent_signal_and_persistence(self):
        model=json.loads(json.dumps(self.model))
        self.assertEqual(model['id'],fingerprint(model))
        for f in [12,15]:
            for result in predict(model,epoch(f,1000)).values():self.assertEqual(result['prediction'],f)
        model['gates']['etrca']['score']+=.1
        self.assertNotEqual(model['id'],fingerprint(model))

    def test_oof_groups_and_learning_curve(self):
        self.assertEqual(len(self.model['oof']),45)
        for cv in self.model['cv'].values():
            self.assertEqual(cv['forced_choice_correct'],30)
            self.assertEqual([x['training_trials_per_target'] for x in cv['learning_curve']],[3,5,10,14])
        with self.assertRaises(ValueError):train([],self.labels,self.groups,['same']*45)

    def test_low_rank_channels(self):
        xs=[np.tile(epoch(f,i)[:,[0]],(1,4)) for i,f in enumerate([12,12,15,15])]
        model=fit(np.array([preprocess(x) for x in xs]),[12,12,15,15])
        self.assertTrue(np.isfinite(model['weights']).all())


class PersonalFlowTests(unittest.TestCase):
    def test_balanced_plan_and_invalid_eval_count(self):
        p=plan(11)
        self.assertEqual(len(p),45)
        self.assertNotEqual(p,plan(12))
        for g in range(15):self.assertEqual(sorted(b['frequency'] or 0 for b in p if b['group']==g),[0,12,15])
        s={'personal':{'model_id':'frozen','evaluation_plan':p},'trials':[]}
        b=dict(p[0],personal_phase='evaluation',personal_slot=0)
        meta=validate_start(s,b)
        s['trials']=[{'frequency':12,'personal':dict(meta,eligible=False),'aborted':True}]
        self.assertEqual(len(pending(s,'evaluation')),44)
        a=summary(s)['algorithms']['etrca'];self.assertEqual(a['target_attempts'],1);self.assertEqual(a['accuracy_all'],0)
        with self.assertRaises(ValueError):validate_start(s,b)

    def test_clock_reconstruction_and_missing_onset(self):
        t=100+np.arange(1200)/200
        x=np.column_stack([np.sin(2*np.pi*12*(t-100))]*4)
        trial={'start_lsl':100,'onset':{'server_time':100,'uncertainty_ms':1}}
        out,diag=aligned_epoch(x,t,trial)
        np.testing.assert_allclose(out,x[200:1000],atol=1e-9)
        self.assertAlmostEqual(diag['estimated_rate_hz'],200)
        self.assertFalse(diag['physical_onset_verified'])
        with self.assertRaises(ValueError):aligned_epoch(x,t,{})
        trial['onset']['uncertainty_ms']=20
        with self.assertRaises(ValueError):aligned_epoch(x,t,trial)

    def test_api_capture_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            receiver=DiagnosticReceiver();clock=[100.]
            app=create_app(receiver,d,lambda:clock[0],native=True);c=app.test_client()
            sid=c.post('/api/session',json={'setup':{'channels':[0,1,2,3],'reference':'A1','ground':'A2'}}).json['id']
            self.assertEqual(c.post('/api/personal/prepare',json={'environment':{'distance_cm':60,'target_cm':4}}).status_code,200)
            self.assertEqual(c.get('/api/personal/plan/evaluation').status_code,400)
            self.assertEqual(c.post('/api/personal/train',json={}).status_code,400)
            b=c.get('/api/personal/plan/calibration').json['blocks'][0]
            started=c.post('/api/block/start',json=b);self.assertEqual(started.status_code,200)
            self.assertEqual(c.post('/api/personal/onset',json={'id':started.json['id'],'server_time':100.,'uncertainty_ms':1,'geometry':{'width':1200,'height':800,'dpr':2,'target_px':150}}).status_code,200)
            self.assertEqual(c.post('/api/personal/onset',json={'id':started.json['id'],'server_time':100.,'uncertainty_ms':1,'geometry':{'width':1200,'height':800,'dpr':2,'target_px':150}}).status_code,400)
            receiver.fill(seconds=6);clock[0]=106
            result=c.post('/api/block/finish',json={'id':started.json['id'],'frame_times_ms':(np.arange(361)*1000/60).tolist()})
            self.assertEqual(result.status_code,200,result.json)
            self.assertTrue(result.json['personal']['eligible'],result.json['personal'])
            self.assertEqual(c.get('/api/personal/status').json['calibration_completed'],1)
            self.assertEqual(c.post('/api/block/start',json=b).status_code,400)
            self.assertTrue((Path(d)/sid/'personal_report.html').exists())
            c.post('/api/session',json={'setup':{'channels':[0]}})
            self.assertEqual(c.post('/api/personal/resume',json={'id':sid}).status_code,200)
            self.assertEqual(c.get('/api/personal/status').json['calibration_completed'],1)
            self.assertEqual(c.post('/api/personal/resume',json={'id':'../x'}).status_code,400)


    def test_full_calibration_freeze_and_independent_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            receiver=DiagnosticReceiver();clock=[100.];rng=np.random.default_rng(5)
            c=create_app(receiver,d,lambda:clock[0],native=True).test_client()
            sid=c.post('/api/session',json={'setup':{'channels':[0,1,2,3],'reference':'A1','ground':'A2'}}).json['id']
            c.post('/api/personal/prepare',json={'environment':{'distance_cm':60,'target_cm':4}})
            def capture(b):
                start=c.post('/api/block/start',json=b);self.assertEqual(start.status_code,200,start.json)
                c.post('/api/personal/onset',json={'id':start.json['id'],'server_time':clock[0],'uncertainty_ms':1,
                    'geometry':{'width':1200,'height':800,'dpr':2,'target_px':150}})
                t=np.arange(1200)/200;x=rng.normal(0,.3,(1200,4))
                if b['frequency']:x+=np.sin(2*np.pi*b['frequency']*t)[:,None]*[5,4,3,2]
                cursor=receiver.cursor();receiver.rows=[(cursor+i+1,clock[0]+v,clock[0]+v,clock[0]+v,row.tolist()) for i,(v,row) in enumerate(zip(t,x))]
                clock[0]+=6
                r=c.post('/api/block/finish',json={'id':start.json['id'],'frame_times_ms':(np.arange(361)*1000/60).tolist()})
                self.assertEqual(r.status_code,200,r.json);self.assertTrue(r.json['personal']['eligible'],r.json['personal'])
            for b in c.get('/api/personal/plan/calibration').json['blocks']:capture(b)
            trained=c.post('/api/personal/train',json={});self.assertEqual(trained.status_code,200,trained.json)
            path=Path(d)/sid/'personal_model.json';frozen=path.read_bytes()
            self.assertEqual(c.post('/api/personal/train',json={}).status_code,400)
            self.assertEqual(c.get('/api/personal/plan/calibration').status_code,400)
            for b in c.get('/api/personal/plan/evaluation').json['blocks'][:3]:capture(b)
            self.assertEqual(path.read_bytes(),frozen)
            for a in c.get('/api/personal/status').json['algorithms'].values():
                self.assertEqual(a['target_attempts'],2);self.assertEqual(a['forced_top1_correct'],2);self.assertEqual(a['control_attempts'],1)
            model=json.loads(frozen);self.assertEqual(len(model['calibration_trial_ids']),45)
            evaluation=c.get('/api/session').json['trials'][-3:]
            self.assertFalse(set(model['calibration_trial_ids'])&{r['id'] for r in evaluation})

if __name__=='__main__':unittest.main()
