import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from app import CONFIG, create_app
from decoder import decode


def signal(frequency=12, rate=200, seconds=5):
    t = np.arange(int(rate * seconds)) / rate
    rng = np.random.default_rng(17)
    x = np.column_stack([15 * np.sin(2 * np.pi * frequency * t + phase) + rng.normal(0, 2, len(t)) for phase in [0.1, 0.7, 1.3, 2]])
    return x, t


class DecoderTests(unittest.TestCase):
    def test_each_target_at_both_sampling_rates(self):
        for fs in [200, 250]:
            for target in CONFIG['targets']:
                x, t = signal(target['frequency'], fs)
                for channels in [[0], [0, 1, 2, 3]]:
                    with self.subTest(fs=fs, target=target, channels=channels):
                        r = decode(x, t, fs, channels, CONFIG, 5)
                        self.assertEqual(r['prediction'], target['id'])

    def test_bad_input_is_rejected(self):
        x, t = signal()
        for data, ts, channels in [(x[:20], t[:20], [0]), (x, t, [4]), (x * 0, t, [0]),
                                   (x * np.nan, t, [0]), (x, t[::-1], [0]), (x, t * 1.5, [0])]:
            self.assertIsNone(decode(data, ts, 200, channels, CONFIG, 5)['prediction'])
        gap = t.copy(); gap[400:] += 0.3
        self.assertIsNone(decode(x, gap, 200, [0], CONFIG, 5)['prediction'])

    def test_noise_and_ambiguous_signal_rejected(self):
        x, t = signal()
        noise = np.random.default_rng(3).normal(size=x.shape)
        self.assertIsNone(decode(noise, t, 200, [0], CONFIG, 5)['prediction'])
        mixed = (np.sin(2*np.pi*10*t) + np.sin(2*np.pi*12*t))[:, None]
        self.assertIsNone(decode(mixed, t, 200, [0], CONFIG, 5)['prediction'])


class FakeReceiver:
    def __init__(self):
        self.info = {'sampling_rate': 200, 'channels': 4, 'name': 'test'}
    def status(self):
        return {'receiving': True, 'connected': True, 'stream': self.info}
    def window(self, start, end):
        x, t = signal()
        return [(float(ts + 100), row) for ts, row in zip(t, x) if start <= ts + 100 <= end]
    def disconnect(self):
        pass


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = 100.0
        self.client = create_app(FakeReceiver(), self.temp.name, lambda: self.clock).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_trial_roundtrip_and_recording(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
        start = self.client.post('/api/trial/start', json={'channels': [0, 1], 'target': 'B'})
        self.assertEqual(start.status_code, 200)
        self.assertEqual(self.client.post('/api/trial/start', json={'channels': [0]}).status_code, 400)
        self.clock = 105.05
        result = self.client.post('/api/trial/stop', json={'id': start.json['id'], 'frame_times_ms': np.linspace(0, 5000, 301).tolist()})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['prediction'], 'B')
        self.assertTrue(result.json['correct'])
        path = Path(self.temp.name) / result.json['recording']
        with np.load(path, allow_pickle=False) as data:
            self.assertEqual(data['samples'].shape, (1000, 4))
            self.assertEqual(json.loads(str(data['metadata']))['channels'], [0, 1])

    def test_validation_abort_and_cross_origin(self):
        self.assertEqual(self.client.post('/api/trial/start', json={'channels': [4]}).status_code, 400)
        self.assertEqual(self.client.post('/api/trial/start', json={'channels': [0]}, headers={'Origin': 'https://example.com'}).status_code, 403)
        r = self.client.post('/api/trial/start', json={'channels': [0]})
        self.client.post('/api/trial/abort', json={})
        self.assertEqual(self.client.post('/api/trial/stop', json={'id': r.json['id']}).status_code, 400)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_bad_display_timing_saves_but_rejects(self):
        r = self.client.post('/api/trial/start', json={'channels': [0]})
        self.clock = 105
        result = self.client.post('/api/trial/stop', json={'id': r.json['id'], 'frame_times_ms': [0, 1000, 5000]})
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json['prediction'])
        self.assertIn('프레임', result.json['reason'])


if __name__ == '__main__':
    unittest.main()
