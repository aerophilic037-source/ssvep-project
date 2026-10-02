"""Opt-in loopback LSL test: GANGLION_LSL_TEST=1 python -m unittest discover ..."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from uuid import uuid4

import numpy as np

from acquisition import Receiver, lsl
from app import create_app


@unittest.skipUnless(os.environ.get('GANGLION_LSL_TEST') == '1', 'requires local LSL sockets')
class LslIntegrationTest(unittest.TestCase):
    def test_live_lsl_to_prediction_and_file(self):
        lib = lsl()
        name = 'Ganglion-TEST-' + uuid4().hex
        info = lib.StreamInfo(name, 'EEG', 4, 200, 'float32', name)
        outlet = lib.StreamOutlet(info)
        stop = threading.Event()

        def send():
            start = lib.local_clock()
            index = 0
            while not stop.is_set():
                stamp = start + index / 200
                if stamp > lib.local_clock():
                    time.sleep(0.001)
                    continue
                outlet.push_sample([20 * np.sin(2*np.pi*12*index/200 + phase) for phase in [0, .3, .7, 1.1]], timestamp=stamp)
                index += 1

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        receiver = Receiver()
        try:
            streams = receiver.discover()
            selected = next(s for s in streams if s['name'] == name)
            receiver.connect(selected['uid'])
            time.sleep(.5)
            self.assertTrue(receiver.status()['receiving'])
            with tempfile.TemporaryDirectory() as folder:
                client = create_app(receiver, folder).test_client()
                r = client.post('/api/trial/start', json={'channels': [0, 1, 2, 3], 'target': 'B'})
                self.assertEqual(r.status_code, 200, r.json)
                time.sleep(5)
                result = client.post('/api/trial/stop', json={'id': r.json['id'], 'frame_times_ms': np.linspace(0, 5000, 301).tolist()})
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual(result.json['prediction'], 'B', result.json)
                with np.load(Path(folder) / result.json['recording']) as data:
                    self.assertGreater(len(data['samples']), 900)
                    metadata = json.loads(str(data['metadata']))
                    self.assertEqual(metadata['stream']['sampling_rate'], 200)
                print('Loopback LSL result:', result.json)
            receiver.disconnect()
            receiver.connect(selected['uid'])
            time.sleep(.3)
            self.assertTrue(receiver.status()['receiving'])
        finally:
            receiver.disconnect()
            stop.set()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
