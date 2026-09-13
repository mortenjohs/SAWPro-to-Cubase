import unittest
from sawpro_to_cubase.timecode import (
    samples_to_seconds,
    seconds_to_samples,
    samples_to_smpte,
    smpte_to_seconds,
)


class TestTimecode(unittest.TestCase):
    def test_samples_to_seconds(self):
        self.assertEqual(samples_to_seconds(0, 44100), 0.0)
        self.assertEqual(samples_to_seconds(44100, 44100), 1.0)
        self.assertEqual(samples_to_seconds(88200, 44100), 2.0)
        self.assertEqual(samples_to_seconds(48000, 48000), 1.0)
        self.assertEqual(samples_to_seconds(100, 0), 0.0)

    def test_seconds_to_samples(self):
        self.assertEqual(seconds_to_samples(0.0, 44100), 0)
        self.assertEqual(seconds_to_samples(1.0, 44100), 44100)
        self.assertEqual(seconds_to_samples(2.5, 48000), 120000)

    def test_samples_to_smpte_30fps(self):
        # 0 samples -> 00:00:00:00
        self.assertEqual(samples_to_smpte(0, 44100, fps=30.0), "00:00:00:00")
        # 1 second (44100 samples) -> 00:00:01:00
        self.assertEqual(samples_to_smpte(44100, 44100, fps=30.0), "00:00:01:00")
        # 1.5 seconds -> 00:00:01:15
        self.assertEqual(samples_to_smpte(66150, 44100, fps=30.0), "00:00:01:15")
        # 60 seconds -> 00:01:00:00
        self.assertEqual(samples_to_smpte(44100 * 60, 44100, fps=30.0), "00:01:00:00")
        # 1 hour -> 01:00:00:00
        self.assertEqual(samples_to_smpte(44100 * 3600, 44100, fps=30.0), "01:00:00:00")

    def test_samples_to_smpte_25fps(self):
        self.assertEqual(samples_to_smpte(48000, 48000, fps=25.0), "00:00:01:00")
        self.assertEqual(samples_to_smpte(24000, 48000, fps=25.0), "00:00:00:12")

    def test_samples_to_smpte_drop_frame(self):
        tc = samples_to_smpte(44100 * 60, 44100, fps=29.97, drop_frame=True)
        self.assertIn(";", tc)

    def test_smpte_to_seconds(self):
        self.assertEqual(smpte_to_seconds("00:00:01:00", fps=30.0), 1.0)
        self.assertEqual(smpte_to_seconds("00:01:00:00", fps=30.0), 60.0)
        self.assertEqual(smpte_to_seconds("01:00:00:00", fps=30.0), 3600.0)


if __name__ == "__main__":
    unittest.main()
