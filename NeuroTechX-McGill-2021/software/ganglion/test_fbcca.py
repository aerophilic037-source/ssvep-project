import unittest
import numpy as np
from fbcca import fbcca_scores

class FBCCATests(unittest.TestCase):
    def test_harmonic_only_response(self):
        # Fundamental is absent: identify 12 Hz from its 24/36/48 Hz responses.
        rng=np.random.default_rng(123);t=np.arange(1200)/200
        x=rng.normal(0,.3,(len(t),4))
        for h in (2,3,4):
            x+=np.sin(2*np.pi*12*h*t)[:,None]*np.array([1,.6,.8,.4])/h
        result=fbcca_scores(x,200,[10,12,15])
        self.assertEqual(max(result['scores'],key=result['scores'].get),'12.0')
        self.assertEqual(len(result['band_correlations']),5)

    def test_targets_and_affine_invariance(self):
        rng=np.random.default_rng(42);t=np.arange(1200)/200
        for target in (10,12,15):
            x=rng.normal(0,.5,(len(t),4))+np.sin(2*np.pi*target*t)[:,None]*[1,.7,.5,.8]
            original=x.copy();a=fbcca_scores(x,200,[10,12,15])['scores']
            b=fbcca_scores(x*np.array([2,3,4,5])+1000,200,[10,12,15])['scores']
            self.assertEqual(float(max(a,key=a.get)),target)
            np.testing.assert_allclose(list(a.values()),list(b.values()),rtol=1e-6,atol=1e-8)
            np.testing.assert_array_equal(x,original)

    def test_constant_and_invalid_input(self):
        scores=fbcca_scores(np.zeros((600,4)),200,[12,15])['scores']
        self.assertTrue(all(v==0 for v in scores.values()))
        for x,fs,targets in [(np.zeros((50,4)),200,[12,15]),(np.zeros((600,4)),180,[12,15]),
                             (np.full((600,4),np.nan),200,[12,15]),(np.zeros((600,4)),200,[12,12])]:
            with self.assertRaises(ValueError):fbcca_scores(x,fs,targets)

if __name__=='__main__':unittest.main()
