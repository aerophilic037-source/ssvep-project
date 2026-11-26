"""Protocol and candidate isolation tests without connecting real hardware."""
import tempfile
import unittest
import numpy as np
from validation_app import create_app, protocol
from test_validation import DiagnosticReceiver

class NativeTests(unittest.TestCase):
    def test_stages_are_balanced(self):
        self.assertEqual(len(protocol('single15')),6)
        for name,n in [('choice2',2),('choice',3)]:
            blocks=protocol(name)
            self.assertEqual(sum(b['condition']=='choice' for b in blocks),n*5)
            self.assertEqual(sum(b['condition']=='no_control' for b in blocks),5)
            self.assertTrue(all(len(b['candidates'])==n for b in blocks))

    def test_native_save_and_two_candidate_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            receiver=DiagnosticReceiver(); clock=[100.]
            client=create_app(receiver,folder,lambda:clock[0],native=True).test_client()
            with client.get('/') as response:
                self.assertIn('1 → 2 → 3',response.text)
            r=client.post('/api/session',json={'setup':{'channels':[0], 'units':'unknown'}})
            self.assertEqual(r.status_code,200)
            setup=client.get('/api/session').json['setup']
            self.assertEqual(setup['units'],'uV');self.assertEqual(setup['lsl_filters'],'off')
            bad=client.post('/api/block/start',json={'condition':'choice','frequency':10,'duration':10,'candidates':[12,15]})
            self.assertEqual(bad.status_code,400)
            start=client.post('/api/block/start',json={'condition':'choice','frequency':12,'duration':10,'candidates':[12,15]})
            receiver.fill();clock[0]=110
            result=client.post('/api/block/finish',json={'id':start.json['id'],'frame_times_ms':(np.arange(601)*1000/60).tolist()})
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['prediction'],12)
            self.assertEqual(result.json['candidates'],[12,15])
            self.assertIsNone(client.get('/api/session').json['summary']['choice']['binomial_p_one_sided'])
