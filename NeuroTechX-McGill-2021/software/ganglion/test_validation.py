"""Failure-oriented tests for the EEG validation workstation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from validation import analyze, compare_trials, display_metrics, dumps, timing_metrics
from validation_app import create_app, protocol, summarize
from validation_io import analyze_recording, load_recording, write_report


def data(seconds=20, freq=12, amplitude=12, seed=41):
    t = np.arange(int(seconds*200))/200
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 3, (len(t), 4)) + amplitude*np.sin(2*np.pi*freq*t[:, None]+np.arange(4)*.2)
    return x, t


class MetricsTests(unittest.TestCase):
    def test_known_sinusoid_units_and_no_double_scaling(self):
        x, t = data()
        a = analyze(x, t, channels=[0], include_plot=False)
        b = analyze(x/1e6, t, units="V", channels=[0], include_plot=False)
        self.assertTrue(a["eligible"])
        self.assertAlmostEqual(a["channels"][0]["alpha_power"], b["channels"][0]["alpha_power"], places=8)
        self.assertEqual(a["channels"][0]["peak_hz"], 12)
        self.assertGreater(a["channels"][0]["snr_db"]["12.0"], 15)
        self.assertEqual(max(a["cca_scores_exploratory"], key=a["cca_scores_exploratory"].get), "12.0")
        self.assertFalse(analyze(x,t,units="unknown")["eligible"])

    def test_bad_timing_never_becomes_a_physiological_pass(self):
        x,t = data()
        reversed_ts=t.copy();reversed_ts[800]=reversed_ts[799]-.01
        gap=t.copy();gap[800:]+=.3
        for stamps in (reversed_ts,gap,t*2.4):
            a=analyze(x,stamps,channels=[0])
            self.assertFalse(a["eligible"])
            self.assertFalse(a["spectral_valid"])
            self.assertIn("plot",a)  # Diagnostics are retained, not thrown away.
        original=reversed_ts.copy()
        analyze(x,reversed_ts,channels=[0])
        np.testing.assert_array_equal(reversed_ts,original)

    def test_gui_paired_timestamps_are_not_missing_samples(self):
        t=np.repeat(np.arange(2000)/100,2)
        r=timing_metrics(t,200,source="gui")
        self.assertTrue(r["ok"])
        self.assertEqual(r["duplicates"],2000)
        self.assertFalse(timing_metrics(t,200,source="lsl")["ok"])

    def test_flat_nonfinite_clipping_and_line_noise(self):
        x,t=data()
        for bad in (x*0,np.clip(x*5000,-15686,15686),x+500*np.sin(2*np.pi*60*t[:,None])):
            self.assertFalse(analyze(bad,t,channels=[0])["signal_ok"])
        x[:,3]=np.nan
        self.assertTrue(analyze(x,t,channels=[0])["eligible"])
        self.assertFalse(analyze(x,t,channels=[0,3])["eligible"])
        json.loads(dumps(analyze(x,t)),parse_constant=lambda x:self.fail(x))

    def test_empty_and_short_recordings(self):
        for n in (0,1,100):
            a=analyze(np.zeros((n,4)),np.arange(n)/200)
            self.assertFalse(a["eligible"])
            json.loads(dumps(a))

    def test_alpha_pairs_and_invalid_blocks_excluded(self):
        records=[]
        for pair in range(3):
            for c,amp in (("eyes_open",3),("eyes_closed",12)):
                x,t=data(freq=10,amplitude=amp,seed=pair)
                records.append({"pair":pair,"condition":c,"analysis":analyze(x,t,channels=[0],include_plot=False)})
        r=compare_trials(records,channels=[0])
        self.assertEqual(r["complete_pairs"],3)
        self.assertTrue(r["channels"][0]["repeatable_increase"])
        records[-1]["analysis"]["eligible"]=False
        r=compare_trials(records,channels=[0])
        self.assertEqual(r["complete_pairs"],2)
        self.assertFalse(r["channels"][0]["repeatable_increase"])

    def test_short_alpha_or_aborted_pair_cannot_count_as_evidence(self):
        x,t=data(seconds=5,freq=10)
        short=analyze(x,t,channels=[0],include_plot=False)
        self.assertTrue(short['eligible'])  # General QC != adequate alpha block.
        records=[{'pair':0,'condition':c,'analysis':short} for c in ('eyes_open','eyes_closed')]
        self.assertEqual(compare_trials(records)['complete_pairs'],0)
        x,t=data(freq=10)
        long=analyze(x,t,channels=[0],include_plot=False)
        records=[{'pair':0,'condition':c,'analysis':long,'aborted':c=='eyes_closed'} for c in ('eyes_open','eyes_closed')]
        self.assertEqual(compare_trials(records)['complete_pairs'],0)

    def test_display_drops_even_with_healthy_median_fps(self):
        frames=np.arange(601)*1000/60
        self.assertTrue(display_metrics(frames,10)["ok"])
        frames[300:]+=500
        self.assertFalse(display_metrics(frames,10)["ok"])
        self.assertFalse(display_metrics([0,0,1],10)["ok"])
        self.assertFalse(display_metrics(np.arange(301)*1000/30,10)["ok"])

    def test_choice_accounting_includes_rejections_and_false_positives(self):
        trials=[{"condition":"choice","frequency":10.,"prediction":10.,"valid_for_decision":True},
                {"condition":"choice","frequency":12.,"prediction":None,"valid_for_decision":False},
                {"condition":"no_control","prediction":15.}]
        s=summarize({"trials":trials,"setup":{"channels":[0]}})["choice"]
        self.assertEqual(s["accuracy_all_attempts"],.5)
        self.assertEqual(s["accuracy_accepted"],1)
        self.assertEqual(s["no_control_false_positives"],1)


class ImportTests(unittest.TestCase):
    def test_gui_api_pairs_without_lsl_and_duplicate_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            gui=root/'gui'/'OpenBCISession_test'
            gui.mkdir(parents=True)
            header='%OpenBCI Raw EXG Data\n%Number of channels = 4\n%Sample Rate = 200 Hz\n%Board = OpenBCI_GUI$BoardGanglionBLE\n'
            header+='Sample Index, EXG Channel 0, EXG Channel 1, EXG Channel 2, EXG Channel 3, Accel Channel 0, Accel Channel 1, Accel Channel 2, Other, Other, Other, Other, Other, Timestamp, Marker Channel, Timestamp (Formatted)\n'
            for name,amp in [('open',3),('closed',12),('other',12)]:
                x,t=data(seconds=12,freq=10,amplitude=amp)
                text=header+''.join(f'{i//2%100}, {v[0]}, {v[1]}, {v[2]}, {v[3]}, 0, 0, 0, 0, 0, 0, 0, 0, {1700000000+(i//2)/100}, 0, date\n' for i,v in enumerate(x))
                (gui/f'OpenBCI-RAW-{name}.txt').write_text(text)
            client=create_app(DiagnosticReceiver(),root/'out',gui_dir=root/'gui').test_client()
            client.post('/api/session',json={'setup':{'channels':[0],'units':'uV'}})
            files=client.get('/api/gui-files').json['files']
            self.assertEqual(len(files),3)
            keys={f['name']:f['key'] for f in files}
            for name,condition in [('open','eyes_open'),('closed','eyes_closed')]:
                payload={'key':keys[f'OpenBCI-RAW-{name}.txt'],'condition':condition,'pair':0,'add_to_session':True}
                result=client.post('/api/gui-analyze',json=payload)
                self.assertEqual(result.status_code,200,result.json)
                self.assertTrue(result.json['analysis']['eligible'])
                self.assertEqual(client.post('/api/gui-analyze',json=payload).status_code,400)
            self.assertEqual(client.get('/api/session').json['summary']['alpha']['complete_pairs'],1)
            self.assertEqual(client.post('/api/gui-analyze',json={'key':keys['OpenBCI-RAW-other.txt'],'condition':'eyes_closed','pair':0,'add_to_session':True}).status_code,400)
            self.assertEqual(client.post('/api/gui-analyze',json={'key':'../../secret'}).status_code,400)
            self.assertEqual(len(list(gui.glob('*.txt'))),3)

    def test_gui_header_mapping_and_malformed_line_report(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"OpenBCI-RAW-test.txt"
            header="%OpenBCI Raw EXG Data\n%Number of channels = 4\n%Sample Rate = 200 Hz\n%Board = OpenBCI_GUI$BoardGanglionBLE\n"
            header+="Sample Index, EXG Channel 0, EXG Channel 1, EXG Channel 2, EXG Channel 3, Accel Channel 0, Accel Channel 1, Accel Channel 2, Other, Other, Other, Other, Other, Timestamp, Marker Channel, Timestamp (Formatted)\n"
            x,t=data(seconds=5)
            rows=[f"{i//2%100}, {v[0]}, {v[1]}, {v[2]}, {v[3]}, 0, 0, 0, 0, 0, 0, 0, 0, {1700000000+t[i]}, 0, date\n" for i,v in enumerate(x)]
            p.write_text(header+''.join(rows))
            d=load_recording(p)
            np.testing.assert_allclose(d["samples"],x)
            self.assertEqual(d["fs"],200)
            self.assertEqual(d["parse_issues"],[])
            with p.open('a') as f:f.write('1,2,3\n')
            a=analyze_recording(p)["analysis"]
            self.assertEqual(len(a["parse_issues"]),1)
            self.assertFalse(a["eligible"])
            self.assertFalse(a["spectral_valid"])

    def test_report_escapes_untrusted_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"report.html"
            write_report(p,{"setup":{"notes":"</script><script>alert(1)</script>"}})
            self.assertNotIn('</script><script>alert(1)',p.read_text())


class DiagnosticReceiver:
    def __init__(self):
        self.info={"sampling_rate":200,"channels":4,"name":"SYNTHETIC-TEST"}
        self.rows=[]
        self.receiving=True
    def cursor(self):return self.rows[-1][0] if self.rows else 0
    def snapshot(self,after=None,seconds=10):return [r for r in self.rows if after is None or r[0]>after]
    def status(self):return {"receiving":self.receiving,"connected":True,"stream":self.info}
    def disconnect(self):pass
    def fill(self,seconds=10,reverse=False):
        x,t=data(seconds=seconds)
        stamps=t.copy()
        if reverse:stamps[500]=stamps[499]-.01
        self.rows=[(i+1,100+stamps[i],100+t[i],100+stamps[i],row.tolist()) for i,row in enumerate(x)]


class WorkstationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.receiver=DiagnosticReceiver()
        self.clock=100
        self.client=create_app(self.receiver,self.tmp.name,lambda:self.clock).test_client()
        setup={"channels":[0],"units":"uV","lsl_filters":"off","reference":"A1","ground":"A2","positions":"O1,O2,Oz,POz"}
        r=self.client.post('/api/session',json={"setup":setup})
        self.assertEqual(r.status_code,200,r.json)
        self.session=r.json['id']
    def tearDown(self):
        # End pending timers without retaining test clients for another minute.
        s=self.client.get('/api/status').json
        if s['active_trial']:
            self.client.post('/api/block/finish',json={'id':s['active_trial']['id'],'aborted':True})
        self.tmp.cleanup()
    def test_saved_success_and_offline_report(self):
        r=self.client.post('/api/block/start',json={'condition':'single','duration':10,'frequency':12.,'pair':0})
        self.assertEqual(r.status_code,200,r.json)
        self.receiver.fill();self.clock=110
        out=self.client.post('/api/block/finish',json={'id':r.json['id'],'frame_times_ms':np.arange(601).tolist()})
        # 600 ms of frames must invalidate a 10 s stimulus even though EEG is clean.
        self.assertFalse(out.json['valid_for_decision'])
        self.assertIsNone(out.json['prediction'])
        p=Path(self.tmp.name)/self.session/out.json['recording']
        with np.load(p,allow_pickle=False) as z:
            self.assertEqual(z['samples'].shape,(2000,4))
            self.assertEqual(len(z['arrival_timestamps']),2000)
        with self.client.get(f'/files/{self.session}/report.html') as report:
            self.assertEqual(report.status_code,200)
        self.assertTrue((p.parent/'session.json').exists())
    def test_valid_classification_and_reversal_is_retained(self):
        r=self.client.post('/api/block/start',json={'condition':'choice','duration':10,'frequency':12.,'pair':0})
        self.receiver.fill();self.clock=110
        out=self.client.post('/api/block/finish',json={'id':r.json['id'],'frame_times_ms':(np.arange(601)*1000/60).tolist()})
        self.assertEqual(out.status_code,200,out.json)
        self.assertEqual(out.json['prediction'],12.)
        self.receiver.rows=[];self.clock=100
        r=self.client.post('/api/block/start',json={'condition':'rest','duration':10})
        self.receiver.fill(reverse=True);self.clock=110
        out=self.client.post('/api/block/finish',json={'id':r.json['id']})
        self.assertFalse(out.json['analysis']['eligible'])
        with np.load(Path(self.tmp.name)/self.session/out.json['recording']) as z:
            self.assertEqual(len(z['samples']),2000)
            self.assertEqual(sum(np.diff(z['timestamps'])<0),1)
    def test_abort_saves_partial_and_idempotent_stop_rejected(self):
        r=self.client.post('/api/block/start',json={'condition':'rest','duration':30})
        self.receiver.fill(seconds=3);self.clock=103
        out=self.client.post('/api/block/finish',json={'id':r.json['id'],'aborted':True,'reason':'Esc'})
        self.assertTrue(out.json['aborted'])
        self.assertFalse(out.json['valid_for_decision'])
        self.assertEqual(self.client.post('/api/block/finish',json={'id':r.json['id']}).status_code,400)
        self.assertEqual(len(list((Path(self.tmp.name)/self.session).glob('*.npz'))),1)
    def test_invalid_input_and_cross_origin(self):
        for body in ({'condition':'rest','duration':600},{'condition':'single','duration':10,'frequency':17},{'condition':'rest','duration':10,'pair':'x'}):
            self.assertEqual(self.client.post('/api/block/start',json=body).status_code,400)
        self.assertEqual(self.client.post('/api/block/start',json={'condition':'rest','duration':10},headers={'Origin':'https://other.test'}).status_code,403)
        self.assertEqual(self.client.post('/api/session',json=[]).status_code,415)
    def test_balanced_protocols(self):
        blocks=protocol('choice')
        self.assertEqual(sum(b['condition']=='no_control' for b in blocks),5)
        for f in [10,12,15]:self.assertEqual(sum(b['frequency']==f for b in blocks),5)
        self.assertEqual(len(protocol('alpha')),6)
        self.assertEqual(len(protocol('single')),18)
        self.assertEqual(len(protocol('single15')),6)

    def test_timeout_saves_partial(self):
        with patch('validation_app.threading.Timer') as timer:
            r=self.client.post('/api/block/start',json={'condition':'rest','duration':5})
            self.assertEqual(r.status_code,200)
            self.receiver.fill(seconds=5);self.clock=118
            timer.call_args.args[1]()
        session=self.client.get('/api/session').json
        self.assertEqual(len(session['trials']),1)
        self.assertTrue(session['trials'][0]['aborted'])
        self.assertIn('제한 시간',session['trials'][0]['abort_reason'])
        self.assertIsNone(self.client.get('/api/status').json['active_trial'])


if __name__ == '__main__':
    unittest.main()
