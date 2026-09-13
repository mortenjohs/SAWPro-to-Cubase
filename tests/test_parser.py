import unittest
from pathlib import Path

from sawpro_to_cubase.parser import parse_edl

DATA_DIR = Path(__file__).parent.parent / "data" / "vals1"


class TestParser(unittest.TestCase):
    def setUp(self):
        self.edl_file = DATA_DIR / "vel.edl"
        self.ed0_file = DATA_DIR / "vel.ed0"

    def test_parse_vel_edl(self):
        if not self.edl_file.is_file():
            self.skipTest(f"Test file not found: {self.edl_file}")

        session = parse_edl(self.edl_file)
        self.assertEqual(session.header.magic, "SAWPLUS32 EDL")
        self.assertEqual(session.header.sample_rate, 44100)
        self.assertEqual(session.header.active_tracks, 3)

        # Verify Soundfiles
        filenames = [sf.filename for sf in session.soundfiles]
        self.assertIn("Git1.wav", filenames)
        self.assertIn("Git2.wav", filenames)
        self.assertIn("Bass.wav", filenames)

        # Verify Regions
        self.assertGreaterEqual(len(session.regions), 3)
        reg_names = [r.name for r in session.regions]
        self.assertTrue(any("Git1.wav" in name for name in reg_names))
        self.assertTrue(any("Git2.wav" in name for name in reg_names))
        self.assertTrue(any("Bass.wav" in name for name in reg_names))

        # Verify Track Placements
        # Track 1
        self.assertIn(1, session.tracks)
        t1_events = session.tracks[1]
        self.assertEqual(len(t1_events), 1)
        self.assertEqual(t1_events[0].start_sample, 0)
        self.assertEqual(t1_events[0].end_sample, 4800512)
        self.assertEqual(t1_events[0].duration_samples, 4800512)

        # Track 2
        self.assertIn(2, session.tracks)
        t2_events = session.tracks[2]
        self.assertEqual(len(t2_events), 1)
        self.assertEqual(t2_events[0].start_sample, 929007)
        self.assertEqual(t2_events[0].end_sample, 4328445)
        self.assertEqual(t2_events[0].duration_samples, 3399438)

        # Track 3
        self.assertIn(3, session.tracks)
        t3_events = session.tracks[3]
        self.assertEqual(len(t3_events), 1)
        self.assertEqual(t3_events[0].start_sample, 25851)
        self.assertEqual(t3_events[0].end_sample, 4624384)
        self.assertEqual(t3_events[0].duration_samples, 4598533)

        # Inactive tracks (Track 4 to 44) should not have active events
        for trk_idx in range(4, 45):
            self.assertNotIn(trk_idx, session.tracks)

    def test_parse_vel_ed0(self):
        if not self.ed0_file.is_file():
            self.skipTest(f"Test file not found: {self.ed0_file}")

        session = parse_edl(self.ed0_file)
        self.assertEqual(session.header.magic, "SAWPLUS32 EDL")
        self.assertEqual(session.header.sample_rate, 44100)
        self.assertEqual(session.header.active_tracks, 3)
        self.assertEqual(len(session.get_resolved_events()), 3)

    def test_missing_file_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            parse_edl("non_existent_file.edl")


if __name__ == "__main__":
    unittest.main()
