import io
import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

from sawpro_to_cubase.web.server import SawWebHandler, SESSION_CACHE

DATA_DIR = Path(__file__).parent.parent / "data" / "vals1"


def make_multipart_body(fields, files, boundary=b"----WebKitFormBoundary7MA4YWxkTrZu0gW"):
    body = bytearray()
    for name, value in fields.items():
        body.extend(b"--" + boundary + b"\r\n")
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8") + b"\r\n")

    for field_name, (filename, file_bytes) in files.items():
        body.extend(b"--" + boundary + b"\r\n")
        body.extend(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        body.extend(file_bytes)
        body.extend(b"\r\n")

    body.extend(b"--" + boundary + b"--\r\n")
    return bytes(body), f"multipart/form-data; boundary={boundary.decode('ascii')}"


class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SawWebHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.0)

    def test_get_root(self):
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            content = resp.read().decode("utf-8")
            self.assertIn("SAWPro", content)
            self.assertIn("DAW Interchange", content)

    def test_get_static_css(self):
        req = urllib.request.Request(f"{self.base_url}/static/app.css")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/css", resp.headers.get("Content-Type", ""))
            content = resp.read().decode("utf-8")
            self.assertIn("--bg-primary", content)

    def test_get_static_js(self):
        req = urllib.request.Request(f"{self.base_url}/static/app.js")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("javascript", resp.headers.get("Content-Type", ""))
            content = resp.read().decode("utf-8")
            self.assertIn("renderResults", content)

    def test_invalid_session(self):
        req = urllib.request.Request(f"{self.base_url}/api/session/nonexistent_12345")
        try:
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 404)
        except urllib.error.HTTPError as e:
            with e:
                self.assertEqual(e.code, 404)
                data = json.loads(e.read().decode("utf-8"))
                self.assertIn("error", data)

    def test_convert_edl_upload(self):
        edl_file = DATA_DIR / "vel.edl"
        if not edl_file.is_file():
            self.skipTest(f"Test file not found: {edl_file}")

        edl_bytes = edl_file.read_bytes()
        fields = {
            "format": "all",
            "fps": "30.0",
            "absolute_paths": "false",
            "embed_audio": "false",
        }
        files = {
            "edl_file": ("vel.edl", edl_bytes),
        }
        body, content_type = make_multipart_body(fields, files)

        req = urllib.request.Request(
            f"{self.base_url}/api/convert",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            result = json.loads(resp.read().decode("utf-8"))

        self.assertIn("session_id", result)
        self.assertEqual(result["session_name"], "vel.edl")
        self.assertEqual(result["sample_rate"], 44100)
        self.assertEqual(result["active_tracks"], 3)
        self.assertIn("events", result)
        self.assertEqual(len(result["events"]), 3)

        # Check export links
        self.assertIn("downloads", result)
        downloads = result["downloads"]
        self.assertIn("vel.aaf", downloads)
        self.assertIn("vel_cubase.xml", downloads)
        self.assertIn("zip_download", result)

        # Test download endpoint
        zip_url = f"{self.base_url}{result['zip_download']}"
        with urllib.request.urlopen(zip_url) as dl_resp:
            self.assertEqual(dl_resp.status, 200)
            self.assertIn("application/zip", dl_resp.headers.get("Content-Type", ""))
            zip_content = dl_resp.read()
            self.assertGreater(len(zip_content), 100)

        # Test download cubase XML
        xml_url = f"{self.base_url}{downloads['vel_cubase.xml']}"
        with urllib.request.urlopen(xml_url) as dl_resp:
            self.assertEqual(dl_resp.status, 200)
            xml_content = dl_resp.read().decode("utf-8")
            self.assertIn("<trackarchive", xml_content)

        # Verify audio endpoints and source timing in events
        self.assertIn("audio_available", result)
        self.assertIn("audio_urls", result)
        self.assertIn("source_in_seconds", result["events"][0])

    def test_convert_with_audio_and_stream(self):
        edl_file = DATA_DIR / "vel.edl"
        if not edl_file.is_file():
            self.skipTest(f"Test file not found: {edl_file}")

        # Create a valid minimal WAV header (44 bytes)
        wav_header = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
        wav_header += (1).to_bytes(2, "little") + (2).to_bytes(2, "little")  # PCM, 2 ch
        wav_header += (44100).to_bytes(4, "little") + (176400).to_bytes(4, "little")  # sr, byte rate
        wav_header += (4).to_bytes(2, "little") + (16).to_bytes(2, "little")  # block align, 16-bit
        wav_header += b"data" + (0).to_bytes(4, "little")

        fields = {"format": "all"}
        files = {
            "edl_file": ("vel.edl", edl_file.read_bytes()),
            "git1": ("Git1.wav", wav_header),
        }
        body, content_type = make_multipart_body(fields, files)

        req = urllib.request.Request(
            f"{self.base_url}/api/convert",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            result = json.loads(resp.read().decode("utf-8"))

        self.assertIn("Git1.wav", result["audio_available"])
        self.assertIn("Git1.wav", result["audio_urls"])
        audio_url = f"{self.base_url}{result['audio_urls']['Git1.wav']}"

        # Test audio streaming endpoint
        with urllib.request.urlopen(audio_url) as audio_resp:
            self.assertEqual(audio_resp.status, 200)
            self.assertEqual(audio_resp.headers.get("Content-Type"), "audio/wav")
            data = audio_resp.read()
            self.assertEqual(data, wav_header)

        # Test streaming nonexistent audio in session returns 404
        nonexistent_url = f"{self.base_url}/api/audio/{result['session_id']}/Nonexistent.wav"
        try:
            with urllib.request.urlopen(nonexistent_url) as bad_resp:
                self.fail("Expected 404")
        except urllib.error.HTTPError as e:
            with e:
                self.assertEqual(e.code, 404)
                data = json.loads(e.read().decode("utf-8"))
                self.assertIn("error", data)

        # Test uploading additional audio to existing session
        extra_fields = {}
        extra_files = {"bass": ("Bass.wav", wav_header)}
        extra_body, extra_ct = make_multipart_body(extra_fields, extra_files)
        upload_req = urllib.request.Request(
            f"{self.base_url}/api/audio/{result['session_id']}",
            data=extra_body,
            headers={"Content-Type": extra_ct},
            method="POST",
        )
        with urllib.request.urlopen(upload_req) as up_resp:
            self.assertEqual(up_resp.status, 200)
            up_result = json.loads(up_resp.read().decode("utf-8"))
            self.assertTrue(up_result["success"])
            self.assertIn("Bass.wav", up_result["uploaded"])

    def test_convert_missing_file(self):
        fields = {"format": "all"}
        files = {}
        body, content_type = make_multipart_body(fields, files)

        req = urllib.request.Request(
            f"{self.base_url}/api/convert",
            data=body,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 400)
        except urllib.error.HTTPError as e:
            with e:
                self.assertEqual(e.code, 400)
                data = json.loads(e.read().decode("utf-8"))
                self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()

