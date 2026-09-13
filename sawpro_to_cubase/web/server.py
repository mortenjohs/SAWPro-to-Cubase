from __future__ import annotations

import email
from email import policy
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..exporters import export_aaf, export_cmx3600, export_csv, export_cubase_xml
from ..parser import get_filename_variants, parse_edl

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# In-memory session cache: session_id -> { "dir": Path, "exports": dict[str, Path], "created_at": float }
SESSION_CACHE: dict[str, dict] = {}
CACHE_LOCK = threading.Lock()
MAX_CACHE_AGE_SECONDS = 3600  # 1 hour


def clean_old_sessions() -> None:
    now = time.time()
    with CACHE_LOCK:
        expired = [sid for sid, data in SESSION_CACHE.items() if now - data["created_at"] > MAX_CACHE_AGE_SECONDS]
        for sid in expired:
            try:
                data = SESSION_CACHE.pop(sid, None)
                if data and "temp_dir" in data:
                    data["temp_dir"].cleanup()
            except Exception as err:
                logger.debug("Error cleaning session %s: %s", sid, err)


class SawWebHandler(BaseHTTPRequestHandler):
    server_version = "SawProWeb/1.0"

    def log_message(self, format: str, *args) -> None:
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)

    def send_json_response(self, data: dict, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json_response({"success": False, "error": message}, status=status)

    def do_GET(self) -> None:
        clean_old_sessions()
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Root: Serve index.html
        if path in ("/", "/index.html"):
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return

        # 2. Static files
        if path.startswith("/static/"):
            rel_name = path[len("/static/"):]
            file_path = (STATIC_DIR / rel_name).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Static file not found")
                return
            mime_type, _ = mimetypes.guess_type(str(file_path))
            self.serve_file(file_path, mime_type or "application/octet-stream")
            return

        # 3. File Downloads: /api/download/<session_id>/<filename>
        if path.startswith("/api/download/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, session_id, raw_filename = parts
                filename = urllib.parse.unquote(raw_filename)
                with CACHE_LOCK:
                    session_data = SESSION_CACHE.get(session_id)
                if not session_data or "exports" not in session_data:
                    self.send_error_json("Download link expired or not found", status=HTTPStatus.NOT_FOUND)
                    return

                exports = session_data["exports"]
                target_file = exports.get(filename)
                if not target_file:
                    for k, v in exports.items():
                        if k.lower() == filename.lower() or k == raw_filename or k.lower() == raw_filename.lower():
                            target_file = v
                            break

                if not target_file or not target_file.is_file():
                    self.send_error_json("Export file missing or not found", status=HTTPStatus.NOT_FOUND)
                    return

                mime_type = "application/octet-stream"
                if filename.endswith(".zip"):
                    mime_type = "application/zip"
                elif filename.endswith(".xml"):
                    mime_type = "application/xml"
                elif filename.endswith(".csv"):
                    mime_type = "text/csv"

                safe_ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', '')
                quoted_name = urllib.parse.quote(filename)

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(target_file.stat().st_size))
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{safe_ascii_name}"; filename*=UTF-8\'\'{quoted_name}'
                )
                self.end_headers()

                with open(target_file, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error_json("Invalid download path", status=HTTPStatus.BAD_REQUEST)
                return

        # 4. Audio Streaming: /api/audio/<session_id>/<filename>
        if path.startswith("/api/audio/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, session_id, filename = parts
                filename = urllib.parse.unquote(filename)
                with CACHE_LOCK:
                    session_data = SESSION_CACHE.get(session_id)
                if not session_data or "audio" not in session_data:
                    self.send_error_json("Session not found or expired", status=HTTPStatus.NOT_FOUND)
                    return

                audio_map = session_data["audio"]
                target_file = audio_map.get(filename) or audio_map.get(filename.lower())
                if not target_file:
                    for v in get_filename_variants(filename):
                        target_file = audio_map.get(v) or audio_map.get(v.lower())
                        if target_file:
                            break

                if not target_file or not target_file.is_file():
                    self.send_error_json(f"Audio file '{filename}' not found", status=HTTPStatus.NOT_FOUND)
                    return

                mime_type = "audio/wav"
                if filename.lower().endswith((".aif", ".aiff")):
                    mime_type = "audio/aiff"

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(target_file.stat().st_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                with open(target_file, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error_json("Invalid audio request path", status=HTTPStatus.BAD_REQUEST)
                return

        # 5. Any other /api/ path returns JSON 404
        if path.startswith("/api/"):
            self.send_error_json("API endpoint not found", status=HTTPStatus.NOT_FOUND)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        clean_old_sessions()
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == "/api/convert":
            self.handle_convert()
            return

        if parsed_url.path.startswith("/api/audio/"):
            self.handle_audio_upload(parsed_url.path)
            return

        if parsed_url.path == "/api/mix/mp3":
            self.handle_mix_mp3(parsed_url)
            return

        if parsed_url.path == "/api/log":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            print(f"[CLIENT LOG] {body}")
            self.send_json_response({"ok": True})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def handle_mix_mp3(self, parsed_url) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self.send_error_json("Empty request body", status=HTTPStatus.BAD_REQUEST)
            return

        lame_bin = shutil.which("lame")
        ffmpeg_bin = shutil.which("ffmpeg")
        if not lame_bin and not ffmpeg_bin:
            self.send_error_json(
                "No MP3 encoder (lame or ffmpeg) is installed on the host. Please export as WAV.",
                status=HTTPStatus.NOT_IMPLEMENTED,
            )
            return

        wav_bytes = self.rfile.read(content_length)
        query = urllib.parse.parse_qs(parsed_url.query)
        base_name = query.get("name", ["mix"])[0]
        safe_name = re.sub(r"[^\w\-.]", "_", Path(base_name).stem) + "_mix.mp3"

        try:
            if lame_bin:
                proc = subprocess.run(
                    [lame_bin, "-b", "320", "-", "-"],
                    input=wav_bytes,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                mp3_bytes = proc.stdout
            else:
                proc = subprocess.run(
                    [ffmpeg_bin, "-y", "-i", "pipe:0", "-b:a", "320k", "-f", "mp3", "pipe:1"],
                    input=wav_bytes,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
                mp3_bytes = proc.stdout
        except Exception as exc:
            logger.error("MP3 conversion failed: %s", exc)
            self.send_error_json(f"MP3 encoding failed: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        quoted_name = urllib.parse.quote(safe_name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(mp3_bytes)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{safe_name}"; filename*=UTF-8\'\'{quoted_name}',
        )
        self.end_headers()
        self.wfile.write(mp3_bytes)

    def handle_audio_upload(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 3:
            self.send_error_json("Invalid audio upload path", status=HTTPStatus.BAD_REQUEST)
            return
        session_id = parts[2]
        with CACHE_LOCK:
            session_data = SESSION_CACHE.get(session_id)
        if not session_data:
            self.send_error_json("Session not found or expired", status=HTTPStatus.NOT_FOUND)
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error_json("Expected multipart/form-data request")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        msg = email.message_from_bytes(
            b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + post_data,
            policy=policy.default,
        )

        audio_dir = session_data.get("audio_dir")
        if not audio_dir:
            self.send_error_json("Session audio directory not configured", status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        uploaded_names = []
        for part in msg.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            filename = part.get_filename()
            if not filename:
                continue
            safe_name = Path(filename).name
            out_file = audio_dir / safe_name
            out_file.write_bytes(part.get_payload(decode=True))
            session_data["audio"][safe_name] = out_file
            session_data["audio"][safe_name.lower()] = out_file
            for v in get_filename_variants(safe_name):
                session_data["audio"][v] = out_file
                session_data["audio"][v.lower()] = out_file
            uploaded_names.append(safe_name)

        self.send_json_response({
            "success": True,
            "uploaded": uploaded_names,
            "audio_available": list({f for f in session_data["audio"].keys() if not f.islower() or f in uploaded_names}),
        })

    def handle_convert(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error_json("Expected multipart/form-data request")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self.send_error_json("Invalid Content-Length header")
            return

        if content_length <= 0 or content_length > 250 * 1024 * 1024:  # 250 MB max
            self.send_error_json("Upload exceeds 250 MB limit or is empty")
            return

        body = self.rfile.read(content_length)

        # Parse multipart body using standard library email.parser
        msg_bytes = f"Content-Type: {content_type}\r\n\r\n".encode("latin-1") + body
        msg = email.message_from_bytes(msg_bytes, policy=policy.default)

        temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(temp_dir.name)

        session_files: list[Path] = []
        audio_files: list[Path] = []
        fps = 30.0
        drop_frame = False
        embed_audio = False

        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()

            if name == "fps":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        fps = float(payload.decode("utf-8").strip())
                except (ValueError, UnicodeDecodeError):
                    pass
                continue

            if name == "drop_frame":
                payload = part.get_payload(decode=True)
                if payload and payload.decode("utf-8").strip().lower() in ("true", "1", "yes"):
                    drop_frame = True
                continue

            if name == "embed_audio":
                payload = part.get_payload(decode=True)
                if payload and payload.decode("utf-8").strip().lower() in ("true", "1", "yes"):
                    embed_audio = True
                continue

            if not filename:
                continue

            # Safe sanitized filename
            safe_name = Path(filename).name
            file_bytes = part.get_payload(decode=True)
            if not file_bytes:
                continue

            saved_file = temp_path / safe_name
            saved_file.write_bytes(file_bytes)

            suffix = saved_file.suffix.lower()
            if suffix in (".edl", ".ed0"):
                session_files.append(saved_file)
            elif suffix in (".wav", ".aif", ".aiff"):
                audio_files.append(saved_file)

        if not session_files:
            temp_dir.cleanup()
            self.send_error_json("No .EDL or .ED0 session file found in upload.")
            return

        # Pick the primary session file (.edl preferred, or first found)
        primary_edl = session_files[0]
        for f in session_files:
            if f.suffix.lower() == ".edl":
                primary_edl = f
                break

        try:
            session = parse_edl(primary_edl, audio_dir=temp_path)
        except Exception as exc:
            temp_dir.cleanup()
            self.send_error_json(f"Failed to parse SAWPro session: {exc}")
            return

        # Generate exports into export subfolder
        export_dir = temp_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        base_name = primary_edl.stem

        session_id = f"saw_{int(time.time())}_{os.urandom(4).hex()}"
        exports_map: dict[str, Path] = {}

        # 1. AAF
        aaf_name = f"{base_name}.aaf"
        aaf_path = export_dir / aaf_name
        try:
            export_aaf(
                session,
                aaf_path,
                fps=fps,
                drop_frame=drop_frame,
                relative_paths=True,
                embed_audio=embed_audio,
            )
            exports_map[aaf_name] = aaf_path
        except Exception as err:
            logger.warning("AAF export failed: %s", err)

        # 2. Cubase XML Track Archive
        xml_name = f"{base_name}_cubase.xml"
        xml_path = export_dir / xml_name
        try:
            export_cubase_xml(session, xml_path, fps=fps, drop_frame=drop_frame, relative_paths=True)
            exports_map[xml_name] = xml_path
        except Exception as err:
            logger.warning("XML export failed: %s", err)

        # 3. CSV
        csv_name = f"{base_name}.csv"
        csv_path = export_dir / csv_name
        try:
            export_csv(session, csv_path, fps=fps, drop_frame=drop_frame, relative_paths=True)
            exports_map[csv_name] = csv_path
        except Exception as err:
            logger.warning("CSV export failed: %s", err)

        # 4. CMX 3600
        cmx_name = f"{base_name}_cmx.edl"
        cmx_path = export_dir / cmx_name
        try:
            export_cmx3600(session, cmx_path, fps=fps, drop_frame=drop_frame, relative_paths=True)
            exports_map[cmx_name] = cmx_path
        except Exception as err:
            logger.warning("CMX export failed: %s", err)

        # 5. ZIP Bundle
        zip_name = f"{base_name}_interchange.zip"
        zip_path = export_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for fname, fpath in exports_map.items():
                zf.write(fpath, arcname=fname)
            # Include source audio files in the zip bundle so it is fully self-contained
            for af in audio_files:
                if af.is_file():
                    zf.write(af, arcname=af.name)
            # Include original SAWPro session file for archiving
            if primary_edl.is_file():
                zf.write(primary_edl, arcname=primary_edl.name)

            # Add a helpful README inside the zip
            readme_content = f"""SAWPro EDL Conversion Bundle
============================
Original Session: {primary_edl.name}
Magic Signature : {session.header.magic}
Sample Rate     : {session.header.sample_rate} Hz
Active Tracks   : {session.header.active_tracks}
Total Placements: {session.total_events_count}

Included DAW Files:
-------------------
- {aaf_name} : Advanced Authoring Format (Cubase Pro / Pro Tools / Logic Pro)
- {xml_name} : Steinberg Cubase Track Archive (File > Import > Track Archive)
- {csv_name} : Plain text spreadsheet of timeline cuts and offsets
- {cmx_name} : CMX 3600 Edit Decision List
- {primary_edl.name} : Original SAWPro binary session file

Generated with sawpro_to_cubase.
"""
            zf.writestr("README.txt", readme_content)
        exports_map[zip_name] = zip_path

        # Cache session files for downloads and audio streaming
        audio_map: dict[str, Path] = {}
        for f in audio_files:
            audio_map[f.name] = f
            audio_map[f.name.lower()] = f
            for v in get_filename_variants(f.name):
                audio_map[v] = f
                audio_map[v.lower()] = f

        with CACHE_LOCK:
            SESSION_CACHE[session_id] = {
                "temp_dir": temp_dir,
                "exports": exports_map,
                "audio": audio_map,
                "audio_dir": temp_path,
                "created_at": time.time(),
            }

        # Build JSON response
        downloads = {
            fname: f"/api/download/{session_id}/{urllib.parse.quote(fname)}" for fname in exports_map.keys()
        }

        # Format timeline events for visual frontend lanes and Web Audio playback
        resolved_events = session.get_resolved_events()
        events_data = []
        total_duration = 0.0
        for ev in resolved_events:
            ev_end = ev.timeline_start_seconds + ev.timeline_duration_seconds
            if ev_end > total_duration:
                total_duration = ev_end
            events_data.append({
                "track": ev.track_number,
                "start_samples": ev.timeline_start_samples,
                "start_seconds": round(ev.timeline_start_seconds, 4),
                "duration_seconds": round(ev.timeline_duration_seconds, 4),
                "source_in_seconds": round(ev.source_in_seconds, 4),
                "source_out_seconds": round(ev.source_out_seconds, 4),
                "start_smpte": ev.timeline_start_smpte,
                "region_name": ev.region_name,
                "soundfile_name": ev.soundfile_name,
            })

        soundfiles_data = []
        for sf in session.soundfiles:
            dur = sf.total_frames / sf.sample_rate if sf.sample_rate else 0.0
            soundfiles_data.append({
                "id": sf.id,
                "filename": sf.filename,
                "original_path": sf.original_path,
                "resolved": sf.resolved_path is not None,
                "channels": sf.channels,
                "sample_rate": sf.sample_rate,
                "duration_seconds": round(dur, 2),
            })

        regions_data = []
        for reg in session.regions:
            regions_data.append({
                "id": reg.id,
                "name": reg.name,
                "soundfile_id": reg.soundfile_id,
                "start_sample": reg.start_sample,
                "end_sample": reg.end_sample,
                "length_samples": reg.length_samples,
            })

        audio_urls = {
            f.name: f"/api/audio/{session_id}/{urllib.parse.quote(f.name)}"
            for f in audio_files
        }

        resp_data = {
            "success": True,
            "session_id": session_id,
            "session_name": primary_edl.name,
            "magic": session.header.magic,
            "sample_rate": session.header.sample_rate,
            "smpte_format": session.header.smpte_format,
            "active_tracks": session.header.active_tracks,
            "total_placements": session.total_events_count,
            "total_duration_seconds": round(total_duration, 3),
            "soundfiles": soundfiles_data,
            "regions": regions_data,
            "events": events_data,
            "downloads": downloads,
            "zip_download": f"/api/download/{session_id}/{urllib.parse.quote(zip_name)}",
            "audio_available": list({f.name for f in audio_files}),
            "audio_urls": audio_urls,
            "track_mutes": session.track_mutes,
            "track_solos": session.track_solos,
        }

        self.send_json_response(resp_data)

    def serve_file(self, file_path: Path, content_type: str) -> None:
        try:
            data = file_path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File read error")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)


def find_free_port(starting_port: int = 8080, max_attempts: int = 20) -> int:
    for port in range(starting_port, starting_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return starting_port


def run_server(
    port: int = 8080,
    host: str = "127.0.0.1",
    open_browser: bool = True,
) -> None:
    actual_port = find_free_port(port)
    server_address = (host, actual_port)
    httpd = ThreadingHTTPServer(server_address, SawWebHandler)

    url = f"http://{host}:{actual_port}/"
    print("=" * 60)
    print(" SAWPro to Cubase Web Application Server")
    print("=" * 60)
    print(f" URL     : {url}")
    print(" Status  : Running (Press Ctrl+C to stop)")
    print("=" * 60)

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server...")
    finally:
        httpd.server_close()
        # Clean up temporary session directories
        with CACHE_LOCK:
            for s in SESSION_CACHE.values():
                if "temp_dir" in s:
                    s["temp_dir"].cleanup()
            SESSION_CACHE.clear()
        print("Web server stopped.")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="sawpro-web",
        description="Launch the interactive web interface for SAWPro EDL to DAW conversion.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8080,
        help="Port to run the web server on (default: 8080).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the web browser on launch.",
    )
    args = parser.parse_args(argv)

    run_server(port=args.port, host=args.host, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
