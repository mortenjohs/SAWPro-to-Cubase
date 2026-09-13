import tempfile
import unittest
import wave
from pathlib import Path

from sawpro_to_cubase.parser import (
    _find_audio_file,
    get_filename_variants,
    parse_edl,
)

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

    def test_filename_variants_transliteration(self):
        # klæpp.wav (CP1252 'æ' 0xE6) <-> klµpp.wav (CP850 'µ' 0xE6)
        variants_ae = get_filename_variants("klæpp.wav")
        self.assertIn("klµpp.wav", variants_ae)

        variants_mu = get_filename_variants("klµpp.wav")
        self.assertIn("klæpp.wav", variants_mu)

        # Other scandinavian characters
        self.assertIn("bl°st.wav", get_filename_variants("bløst.wav"))
        self.assertIn("bløst.wav", get_filename_variants("bl°st.wav"))

    def test_find_audio_file_transliteration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create a file on disk with the OEM codepage transliteration name: klµpp.wav
            actual_file = tmppath / "klµpp.wav"
            with wave.open(str(actual_file), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"\x00\x00" * 1000)

            # Look for session name: klæpp.wav
            resolved = _find_audio_file("klæpp.wav", [tmppath], min_frames=500)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.name, "klµpp.wav")

    def test_find_audio_file_length_verification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create a short file on disk: 500 frames
            short_file = tmppath / "klµpp.wav"
            with wave.open(str(short_file), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(b"\x00\x00" * 500)

            # If the session requires at least 2000 frames, short_file should be rejected
            resolved_too_short = _find_audio_file("klæpp.wav", [tmppath], min_frames=2000)
            self.assertIsNone(resolved_too_short)

            # If the session requires at most 400 frames, it should be accepted
            resolved_ok = _find_audio_file("klæpp.wav", [tmppath], min_frames=400)
            self.assertIsNotNone(resolved_ok)
            self.assertEqual(resolved_ok.name, "klµpp.wav")


if __name__ == "__main__":
    unittest.main()
