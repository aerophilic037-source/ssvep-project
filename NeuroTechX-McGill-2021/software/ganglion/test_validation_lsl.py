"""Real LSL sockets with synthetic data: capture, save, and reject corrupt time."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from uuid import uuid4

import numpy as np

from acquisition import Receiver, lsl
from validation_app import create_app


@unittest.skipUnless(os.environ.get("GANGLION_LSL_TEST")=="1", "requires local LSL sockets")
class ValidationLslTest(unittest.TestCase):
    def test_live_capture_and_reversed_timestamp_preservation(self):
        lib=lsl()
        name="VALIDATION-SYNTHETIC-"+uuid4().hex
        outlet=lib.StreamOutlet(lib.StreamInfo(name,"EEG",4,200,"float32",name))
        stop=threading.Event()
        corrupt=threading.Event()
        def send():
            start=lib.local_clock();i=0
            rng=np.random.default_rng(4)
            while not stop.is_set():
                stamp=start+i/200
                if stamp>lib.local_clock():
                    time.sleep(.001);continue
                row=rng.normal(0,2,4)+12*np.sin(2*np.pi*12*i/200+np.arange(4)*.2)
                if corrupt.is_set() and i%100==0:stamp-=.02
                outlet.push_sample(row.tolist(),timestamp=stamp);i+=1
        sender=threading.Thread(target=send,daemon=True);sender.start()
        receiver=Receiver()
        try:
            streams=receiver.discover()
            receiver.connect(next(s["uid"] for s in streams if s["name"]==name))
            time.sleep(.3)
            with tempfile.TemporaryDirectory() as folder:
                client=create_app(receiver,folder).test_client()
                session=client.post('/api/session',json={'setup':{'channels':[0],'units':'uV','lsl_filters':'off'}}).json['id']
                for bad in [False,True]:
                    if bad:corrupt.set()
                    r=client.post('/api/block/start',json={'condition':'single','frequency':12,'duration':5,'pair':int(bad)})
                    self.assertEqual(r.status_code,200,r.json)
                    time.sleep(5)
                    result=client.post('/api/block/finish',json={'id':r.json['id'],'frame_times_ms':(np.arange(301)*1000/60).tolist()})
                    self.assertEqual(result.status_code,200,result.json)
                    self.assertEqual(result.json['analysis']['eligible'],not bad,result.json['analysis']['timing'])
                    self.assertEqual(result.json['prediction'],None if bad else 12.)
                    with np.load(Path(folder)/session/result.json['recording'],allow_pickle=False) as z:
                        self.assertGreater(len(z['samples']),950)
                        self.assertEqual(len(z['arrival_timestamps']),len(z['samples']))
                        self.assertTrue(np.all(np.diff(z['sequence'])==1))
                        self.assertEqual(bool(np.any(np.diff(z['timestamps'])<0)),bad)
                    print('Validation LSL', 'corrupt' if bad else 'clean', result.json['analysis']['timing'],flush=True)
        finally:
            receiver.disconnect();stop.set();sender.join(timeout=2)


if __name__=='__main__':unittest.main()
