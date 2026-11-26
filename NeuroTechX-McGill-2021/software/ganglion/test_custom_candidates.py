import unittest
import numpy as np
from validation import cca_scores
from validation_app import create_app
from test_validation import DiagnosticReceiver
import tempfile

class CustomCandidatesTests(unittest.TestCase):
    def test_twenty_candidate_signal(self):
        frequencies=[8+i*.5 for i in range(20)]
        t=np.arange(1200)/200
        scores=cca_scores(np.sin(2*np.pi*13.5*t)[:,None],200,frequencies)
        self.assertEqual(len(scores),20)
        self.assertEqual(float(max(scores,key=scores.get)),13.5)

    def test_invalid_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            client=create_app(DiagnosticReceiver(),folder,lambda:100.,native=True).test_client()
            client.post('/api/session',json={'setup':{'channels':[0],'units':'unknown'}})
            for candidates in ([8]*2, list(range(21)), [None], [7,10]):
                response=client.post('/api/block/start',json={'condition':'choice','frequency':10,'duration':6,'candidates':candidates})
                self.assertEqual(response.status_code,400)
