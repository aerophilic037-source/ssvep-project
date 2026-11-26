import unittest
import numpy as np
from validation import analyze

class NotchTests(unittest.TestCase):
    def test_line_reduction_and_raw_preservation(self):
        t=np.arange(4000)/200
        x=np.tile((10*np.sin(2*np.pi*12*t)+100*np.sin(2*np.pi*60*t))[:,None],(1,4))
        original=x.copy()
        raw=analyze(x,t,channels=[0])
        cleaned=analyze(x,t,channels=[0],notch_hz=60)
        self.assertFalse(raw['eligible'])
        self.assertTrue(cleaned['eligible'])
        self.assertLess(cleaned['channels'][0]['line60_power_after'],raw['channels'][0]['line60_power_before']*.01)
        self.assertEqual(raw['channels'][0]['raw_std_uv'],cleaned['channels'][0]['raw_std_uv'])
        np.testing.assert_array_equal(x,original)

    def test_notch_does_not_hide_rail_or_flat(self):
        t=np.arange(2000)/200
        for x in (np.zeros((2000,4)),np.full((2000,4),16000.)):
            self.assertFalse(analyze(x,t,notch_hz=60)['eligible'])
