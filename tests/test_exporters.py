import csv
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from sawpro_to_cubase.exporters import (
    export_aaf,
    export_cmx3600,
    export_csv,
    export_cubase_xml,
)
from sawpro_to_cubase.parser import parse_edl

DATA_DIR = Path(__file__).parent.parent / "data" / "vals1"


class TestExporters(unittest.TestCase):
    def setUp(self):
        self.edl_file = DATA_DIR / "vel.edl"
        if not self.edl_file.is_file():
            self.skipTest(f"Test file not found: {self.edl_file}")
        self.session = parse_edl(self.edl_file)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_csv(self):
        csv_file = self.out_dir / "test.csv"
        res = export_csv(self.session, csv_file)
        self.assertTrue(res.is_file())

        with open(res, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 3)

            # Check expected columns
            expected_cols = [
                "Track",
                "StartTime_Samples",
                "StartTime_Seconds",
                "Duration_Samples",
                "Duration_Seconds",
                "StartTime_SMPTE",
                "SoundfileName",
                "RegionName",
            ]
            for col in expected_cols:
                self.assertIn(col, reader[0])

            # Check Track 1 values
            t1 = reader[0]
            self.assertEqual(t1["Track"], "1")
            self.assertEqual(t1["StartTime_Samples"], "0")
            self.assertEqual(t1["Duration_Samples"], "4800512")
            self.assertEqual(t1["SoundfileName"], "Git1.wav")

            # Check Track 2 values
            t2 = reader[1]
            self.assertEqual(t2["Track"], "2")
            self.assertEqual(t2["StartTime_Samples"], "929007")
            self.assertEqual(t2["Duration_Samples"], "3399438")
            self.assertEqual(t2["SoundfileName"], "Git2.wav")

            # Check relative path by default
            self.assertFalse(t1["AudioFilePath"].startswith("/"))

        # Check absolute path override
        csv_abs_file = self.out_dir / "test_abs.csv"
        export_csv(self.session, csv_abs_file, relative_paths=False)
        with open(csv_abs_file, "r", encoding="utf-8") as f:
            reader_abs = list(csv.DictReader(f))
            self.assertTrue(reader_abs[0]["AudioFilePath"].startswith("/"))

    def test_export_cmx3600(self):
        cmx_file = self.out_dir / "test_cmx.edl"
        res = export_cmx3600(self.session, cmx_file)
        self.assertTrue(res.is_file())

        content = res.read_text(encoding="ascii")
        self.assertIn("TITLE:", content)
        self.assertIn("FCM: NON-DROP FRAME", content)
        self.assertIn("001", content)
        self.assertIn("002", content)
        self.assertIn("003", content)
        self.assertIn("* FROM CLIP NAME:", content)
        self.assertIn("* AUDIO PATH:", content)

    def test_export_cubase_xml(self):
        xml_file = self.out_dir / "test_cubase.xml"
        res = export_cubase_xml(self.session, xml_file)
        self.assertTrue(res.is_file())

        tree = ET.parse(str(res))
        root = tree.getroot()
        self.assertEqual(root.tag, "trackarchive")

        # Verify Setup
        setup = root.find("setup")
        self.assertIsNotNone(setup)
        self.assertEqual(setup.find("sampleRate").text, "44100")

        # Verify Media Pool
        pool = root.find("mediapool")
        self.assertIsNotNone(pool)
        audio_nodes = pool.findall("audio")
        self.assertEqual(len(audio_nodes), len(self.session.soundfiles))

        # Check relative path by default in audio pool
        rel_path = audio_nodes[0].find("resolvedPath").text
        self.assertIsNotNone(rel_path)
        self.assertFalse(rel_path.startswith("/"))

        # Verify Tracks
        tracks = root.find("tracks")
        self.assertIsNotNone(tracks)
        track_nodes = tracks.findall("track")
        self.assertEqual(len(track_nodes), 3)

        # Verify Event Attributes on Track 1
        t1 = track_nodes[0]
        events = t1.find("events").findall("event")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get("startSamples"), "0")
        self.assertEqual(events[0].get("lengthSamples"), "4800512")

        # Check absolute path override
        xml_abs = self.out_dir / "test_cubase_abs.xml"
        export_cubase_xml(self.session, xml_abs, relative_paths=False)
        tree_abs = ET.parse(str(xml_abs))
        abs_p = tree_abs.getroot().find("mediapool").findall("audio")[0].find("resolvedPath").text
        self.assertTrue(abs_p.startswith("/"))

    def test_export_aaf_embedded(self):
        try:
            import aaf2
        except ImportError:
            self.skipTest("pyaaf2 not installed")

        aaf_file = self.out_dir / "test_embedded.aaf"
        res = export_aaf(self.session, aaf_file, relative_paths=True, embed_audio=True)
        self.assertTrue(res.is_file())
        # Embedded audio should contain PCM essence data (> 20 MB)
        self.assertGreater(res.stat().st_size, 20_000_000)

        # Verify AAF structure
        with aaf2.open(str(res), "r") as f:
            top_mobs = list(f.content.toplevel())
            self.assertEqual(len(top_mobs), 1)
            comp = top_mobs[0]
            self.assertEqual(len(comp.slots), 4)

            # Check essence data is embedded
            self.assertEqual(len(list(f.content.essencedata)), 3)

            # Slot 0: Timecode
            s0 = comp.slots[0]
            self.assertEqual(s0.name, "Timecode slot")
            self.assertEqual(type(s0.segment).__name__, "Timecode")

            # Slot 1: Track 01
            s1 = comp.slots[1]
            self.assertEqual(s1.name, "Track 01")
            self.assertEqual(len(s1.segment.components), 1)
            self.assertEqual(s1.segment.components[0].length, 4800512)

            # Slot 2: Track 02 (Filler then SourceClip)
            s2 = comp.slots[2]
            self.assertEqual(s2.name, "Track 02")
            self.assertEqual(len(s2.segment.components), 2)
            self.assertEqual(type(s2.segment.components[0]).__name__, "Filler")
            self.assertEqual(s2.segment.components[0].length, 929007)
            self.assertEqual(type(s2.segment.components[1]).__name__, "SourceClip")
            self.assertEqual(s2.segment.components[1].length, 3399438)

            # Slot 3: Track 03 (Filler then SourceClip)
            s3 = comp.slots[3]
            self.assertEqual(s3.name, "Track 03")
            self.assertEqual(len(s3.segment.components), 2)
            self.assertEqual(type(s3.segment.components[0]).__name__, "Filler")
            self.assertEqual(s3.segment.components[0].length, 25851)
            self.assertEqual(type(s3.segment.components[1]).__name__, "SourceClip")
            self.assertEqual(s3.segment.components[1].length, 4598533)

    def test_export_aaf_linked(self):
        try:
            import aaf2
        except ImportError:
            self.skipTest("pyaaf2 not installed")

        aaf_file = self.out_dir / "test_linked.aaf"
        res = export_aaf(self.session, aaf_file, relative_paths=True, embed_audio=False)
        self.assertTrue(res.is_file())
        # Linked file without essence should be compact (< 1 MB)
        self.assertLess(res.stat().st_size, 1_000_000)

        with aaf2.open(str(res), "r") as f:
            # Essence data should be empty
            self.assertEqual(len(list(f.content.essencedata)), 0)
            # MasterMobs should still exist
            master_mobs = [m for m in f.content.mobs if m.__class__.__name__ == "MasterMob"]
            self.assertEqual(len(master_mobs), 3)


if __name__ == "__main__":
    unittest.main()
