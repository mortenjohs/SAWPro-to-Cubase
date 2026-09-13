from __future__ import annotations

import logging
import re
import struct
import wave
from pathlib import Path
from typing import Optional

from .models import (
    SawHeader,
    SawRegion,
    SawSession,
    SawSoundfile,
    SawTrackEvent,
)

logger = logging.getLogger(__name__)


def _find_audio_file(filename: str, candidate_dirs: list[Path]) -> Optional[Path]:
    """Find a file case-insensitively in a list of candidate directories."""
    if not filename:
        return None

    target_lower = filename.lower()
    for directory in candidate_dirs:
        if not directory or not directory.is_dir():
            continue
        direct = directory / filename
        if direct.is_file():
            return direct
        for entry in directory.iterdir():
            if entry.name.lower() == target_lower and entry.is_file():
                return entry

    return None


def _probe_wav_info(file_path: Path) -> tuple[int, int, int]:
    """Extract (sample_rate, channels, frame_count) from a WAV file using stdlib wave."""
    try:
        with wave.open(str(file_path), "rb") as w:
            return w.getframerate(), w.getnchannels(), w.getnframes()
    except Exception as exc:
        logger.debug("Failed to read WAV header for %s: %s", file_path, exc)
        return 0, 0, 0


def _find_chunk_by_tag(data: bytes, tag_prefix: bytes) -> Optional[tuple[int, int, int, int]]:
    """
    Search for an 8-byte chunk tag followed by count (uint32) and stride (uint32).
    Returns (tag_pos, data_pos, count, stride) or None.
    """
    pos = 0
    while True:
        pos = data.find(tag_prefix, pos)
        if pos == -1:
            return None
        # Tag header is at least 16 bytes: 8 bytes tag + 4 bytes count + 4 bytes stride
        if pos + 16 <= len(data):
            count, stride = struct.unpack_from("<II", data, pos + 8)
            # Basic sanity check on count and stride
            if 0 <= count < 100000 and 0 < stride < 65536:
                return pos, pos + 16, count, stride
        pos += 1


def parse_edl(file_path: Path | str, audio_dir: Optional[Path | str] = None) -> SawSession:
    """
    Parse an IQS SAWPro / SAW32 binary .EDL session file.

    :param file_path: Path to the .EDL or .ED0 file.
    :param audio_dir: Optional directory containing source audio (.wav) files.
    :return: Parsed SawSession instance.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"EDL file not found: {path}")

    data = path.read_bytes()
    if len(data) < 64:
        raise ValueError(f"File too small to be a valid SAW EDL file ({len(data)} bytes)")

    # 1. Parse Magic Signature
    raw_magic = data[0:16]
    clean_magic = raw_magic.split(b"\x00")[0].decode("ascii", errors="replace").strip()

    # 2. Parse Sample Rate (SRATE tag or scanning)
    srate = 44100
    srate_pos = data.find(b"SRATE")
    if srate_pos != -1 and srate_pos + 12 <= len(data):
        candidate_srate = struct.unpack_from("<I", data, srate_pos + 8)[0]
        if 8000 <= candidate_srate <= 192000:
            srate = candidate_srate
    else:
        # Fallback: scan for standard sample rates
        for standard_sr in [44100, 48000, 88200, 96000]:
            if struct.pack("<I", standard_sr) in data[:64]:
                srate = standard_sr
                break

    # 3. Parse SMPTE format code
    smpte_val = 0
    smpte_pos = data.find(b"SMPTE")
    if smpte_pos != -1 and smpte_pos + 12 <= len(data):
        smpte_val = struct.unpack_from("<I", data, smpte_pos + 8)[0]

    header = SawHeader(
        magic=clean_magic,
        sample_rate=srate,
        smpte_format=smpte_val,
        active_tracks=0,
    )

    # Candidate directories for resolving audio
    candidate_dirs: list[Path] = [path.parent]
    if audio_dir:
        candidate_dirs.insert(0, Path(audio_dir).resolve())

    # 4. Parse Soundfiles (FILES chunk)
    soundfiles: list[SawSoundfile] = []
    files_chunk = _find_chunk_by_tag(data, b"FILES")
    if files_chunk:
        _, data_pos, count, stride = files_chunk
        for i in range(count):
            offset = data_pos + i * stride
            if offset + stride > len(data):
                break
            record = data[offset : offset + stride]
            # Check for empty/unused slot
            if record.startswith(b"\xff\xff\xff\xff"):
                continue

            # Path is null-terminated ASCII
            raw_path = record.split(b"\x00")[0]
            orig_path = raw_path.decode("latin1", errors="replace").strip()
            if not orig_path or orig_path.startswith("\xff"):
                continue

            clean_fn = orig_path.replace("\\", "/").split("/")[-1]
            resolved = _find_audio_file(clean_fn, candidate_dirs)
            sf_sr, channels, frames = _probe_wav_info(resolved) if resolved else (0, 0, 0)

            soundfiles.append(
                SawSoundfile(
                    id=i,
                    original_path=orig_path,
                    resolved_path=resolved,
                    filename=clean_fn,
                    sample_rate=sf_sr or srate,
                    channels=channels,
                    total_frames=frames,
                )
            )

    # 5. Parse Regions (REGIONS chunk)
    regions: list[SawRegion] = []
    regions_chunk = _find_chunk_by_tag(data, b"REGIONS")
    if regions_chunk:
        _, data_pos, count, stride = regions_chunk
        for i in range(count):
            offset = data_pos + i * stride
            if offset + stride > len(data):
                break
            record = data[offset : offset + stride]

            # Check if empty slot (all 0xFF or begins with sentinel)
            first_int = struct.unpack_from("<I", record, 0)[0]
            if first_int in (0xFFFFFFFF, 0xFFFFFFFE):
                # May still have a name or be unused
                raw_name = record[4:68].split(b"\x00")[0]
                if not raw_name or raw_name.startswith(b"\xff") or raw_name.startswith(b"\xfe"):
                    continue

            name_bytes = record[4:68].split(b"\x00")[0]
            name = name_bytes.decode("latin1", errors="replace").strip()
            if not name or name.startswith("\xff") or name.startswith("\xfe"):
                continue

            # In-point and Out-point
            # In SAWPLUS32: offset 104 is in-point, offset 108 is out-point / length, offset 112 is soundfile ID
            in_point = 0
            out_point = 0
            sf_id = 0
            if len(record) >= 116:
                in_point, out_point, sf_id = struct.unpack_from("<III", record, 104)

            # Defensive validation of values
            if sf_id == 0xFFFFFFFF:
                sf_id = 0

            length = out_point - in_point if out_point >= in_point else out_point

            regions.append(
                SawRegion(
                    id=i,
                    name=name,
                    soundfile_id=sf_id,
                    start_sample=in_point,
                    end_sample=out_point,
                    length_samples=length,
                )
            )

    # 6. Parse Track Events (TRACK01 to TRACKxx)
    tracks: dict[int, list[SawTrackEvent]] = {}
    for match in re.finditer(rb"TRACK(\d{2})\s*\x00", data):
        track_num = int(match.group(1))
        pos = match.start()
        if pos + 16 > len(data):
            continue

        count, stride = struct.unpack_from("<II", data, pos + 8)
        if count <= 0 or stride < 12 or count > 10000:
            continue

        events_on_track: list[SawTrackEvent] = []
        data_pos = pos + 16

        for e in range(count):
            entry_offset = data_pos + e * stride
            if entry_offset + stride > len(data):
                break
            entry_bytes = data[entry_offset : entry_offset + stride]

            # Inactive or empty sentinel entries start with 0xFFFFFFFF
            if entry_bytes.startswith(b"\xff\xff\xff\xff"):
                continue

            # Standard 48-byte track entry layout:
            # uint32: region_id
            # uint32: timeline_start_samples
            # uint32: timeline_end_samples
            region_id, tl_start, tl_end = struct.unpack_from("<III", entry_bytes, 0)

            # Skip entries with invalid values
            if region_id == 0xFFFFFFFF:
                continue
            if tl_end < tl_start:
                continue

            duration = tl_end - tl_start
            events_on_track.append(
                SawTrackEvent(
                    track_number=track_num,
                    region_id=region_id,
                    start_sample=tl_start,
                    end_sample=tl_end,
                    duration_samples=duration,
                )
            )

        if events_on_track:
            tracks[track_num] = events_on_track

    header.active_tracks = len(tracks)

    return SawSession(
        header=header,
        soundfiles=soundfiles,
        regions=regions,
        tracks=tracks,
        source_path=path,
    )
