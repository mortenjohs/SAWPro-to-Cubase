from __future__ import annotations

import logging
import re
import struct
import wave
import unicodedata
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


def get_filename_variants(name: str) -> set[str]:
    """
    Generate character-encoding and Unicode normalization variants
    for a filename across Windows-1252, DOS CP850/CP865/CP437, MacRoman, and UTF-8.
    Catches common legacy mismatches like klæpp.wav <-> klµpp.wav.
    """
    if not name:
        return set()

    variants: set[str] = {name, name.lower()}

    # Unicode normalizations (NFC, NFD, NFKC, NFKD)
    for norm in ("NFC", "NFD", "NFKC", "NFKD"):
        try:
            n = unicodedata.normalize(norm, name)
            variants.add(n)
            variants.add(n.lower())
        except Exception:
            pass

    # Direct common transliterations between Windows ANSI (CP1252) and DOS OEM (CP850, CP865, CP437)
    char_pairs = [
        # Windows-1252 byte decoded as CP850 / CP865 / CP437
        ("æ", "µ"), ("ø", "°"), ("å", "Õ"), ("å", "σ"),
        ("Æ", "ã"), ("Æ", "╞"), ("Ø", "Ï"), ("Ø", "╪"), ("Å", "┼"),
        ("é", "Ú"), ("é", "Θ"), ("ä", "õ"), ("ä", "Σ"), ("ö", "÷"), ("ü", "³"), ("ü", "ⁿ"),
        # DOS OEM byte decoded as Windows-1252
        ("æ", "‘"), ("ø", "›"), ("å", "†"),
        ("Æ", "’"), ("é", "‚"), ("ä", "„"), ("ö", "”"),
    ]

    for a, b in char_pairs:
        if a in name:
            v = name.replace(a, b)
            variants.add(v)
            variants.add(v.lower())
        if b in name:
            v = name.replace(b, a)
            variants.add(v)
            variants.add(v.lower())

    # Codepage roundtrip matrix
    codepages = ("cp1252", "cp850", "cp865", "cp437", "mac_roman", "latin1", "utf-8")
    for enc in codepages:
        try:
            raw = name.encode(enc, errors="replace")
            for dec in codepages:
                if dec != enc:
                    try:
                        alt = raw.decode(dec, errors="ignore")
                        if alt and len(alt) >= len(name) - 2:
                            variants.add(alt)
                            variants.add(alt.lower())
                            variants.add(unicodedata.normalize("NFC", alt).lower())
                    except Exception:
                        pass
        except Exception:
            pass

    return variants


def _find_audio_file(
    filename: str,
    candidate_dirs: list[Path],
    min_frames: int = 0,
) -> Optional[Path]:
    """
    Multi-pass resolver for legacy audio filenames:
    Pass 1: Direct exact match.
    Pass 2: Case-insensitive match.
    Pass 3: Character-encoding & codepage transliteration match (e.g. klæpp.wav <-> klµpp.wav).
    Pass 4: Skeleton / alphanumeric match with audio frame length verification.
    """
    if not filename:
        return None

    target_lower = filename.lower()
    target_variants = {v.lower() for v in get_filename_variants(filename)}

    # Pass 1: Direct exact match
    for directory in candidate_dirs:
        if not directory or not directory.is_dir():
            continue
        direct = directory / filename
        if direct.is_file():
            return direct

    # Pass 2: Case-insensitive match
    for directory in candidate_dirs:
        if not directory or not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and entry.name.lower() == target_lower:
                return entry

    # Pass 3: Codepage & transliteration variants match
    for directory in candidate_dirs:
        if not directory or not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            entry_lower = entry.name.lower()
            matched = False
            if entry_lower in target_variants:
                matched = True
            elif any(v.lower() in target_variants for v in get_filename_variants(entry.name)):
                matched = True

            if matched:
                if min_frames > 0:
                    _, _, frames = _probe_wav_info(entry)
                    if 0 < frames < min_frames:
                        logger.warning(
                            "Found variant '%s' for '%s', but file length (%d frames) is shorter than required (%d frames)",
                            entry.name, filename, frames, min_frames
                        )
                        continue
                return entry

    # Pass 4: Skeleton match + audio length verification
    def skeleton(s: str) -> str:
        stem = Path(s).stem.lower()
        return "".join(c for c in stem if c.isalnum())

    target_skel = skeleton(filename)
    target_ext = Path(filename).suffix.lower()

    if target_skel:
        candidates: list[tuple[Path, int]] = []
        for directory in candidate_dirs:
            if not directory or not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if not entry.is_file() or entry.suffix.lower() != target_ext:
                    continue
                entry_skel = skeleton(entry.name)
                if entry_skel == target_skel or (len(entry_skel) >= 3 and (entry_skel in target_skel or target_skel in entry_skel)):
                    sr, ch, frames = _probe_wav_info(entry)
                    if min_frames > 0:
                        if frames >= min_frames:
                            candidates.append((entry, frames))
                    else:
                        candidates.append((entry, frames))

        if candidates:
            if min_frames > 0:
                candidates.sort(key=lambda c: abs(c[1] - min_frames))
            return candidates[0][0]

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

    # 5b. Second-Pass Audio File Resolution:
    # For any soundfile that was not resolved in the first pass, run deep resolution
    # checking codepage transliterations (e.g. klæpp.wav <-> klµpp.wav) and verifying
    # that candidate audio files satisfy the minimum frame count required by regions.
    for sf in soundfiles:
        if not sf.resolved_path:
            sf_regions = [r for r in regions if r.soundfile_id == sf.id]
            min_frames = max([r.end_sample for r in sf_regions], default=0)
            resolved = _find_audio_file(sf.filename, candidate_dirs, min_frames=min_frames)
            if resolved:
                sf.resolved_path = resolved
                sf_sr, channels, frames = _probe_wav_info(resolved)
                sf.sample_rate = sf_sr or srate
                sf.channels = channels
                sf.total_frames = frames
                logger.info(
                    "Resolved audio file on pass 2: '%s' -> '%s' (min_frames=%d, frames=%d)",
                    sf.filename,
                    resolved.name,
                    min_frames,
                    frames,
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

    # 7. Parse Track Mute and Solo States (MUTE and SOLO chunks)
    max_track = max(tracks.keys(), default=44) if tracks else 44
    track_mutes: dict[int, bool] = {}
    match_mute = re.search(rb"MUTE\s*\x00", data)
    if match_mute:
        pos = match_mute.end()
        if pos + 44 * 4 <= len(data):
            vals = struct.unpack_from("<44I", data, pos)
            for trk_idx, val in enumerate(vals, 1):
                if val != 0 and trk_idx <= max_track:
                    track_mutes[trk_idx] = True

    track_solos: dict[int, bool] = {}
    match_solo = re.search(rb"SOLO\s*\x00", data)
    if match_solo:
        pos = match_solo.end()
        if pos + 44 * 4 <= len(data):
            vals = struct.unpack_from("<44I", data, pos)
            for trk_idx, val in enumerate(vals, 1):
                if val != 0 and trk_idx <= max_track:
                    track_solos[trk_idx] = True

    return SawSession(
        header=header,
        soundfiles=soundfiles,
        regions=regions,
        tracks=tracks,
        track_mutes=track_mutes,
        track_solos=track_solos,
        source_path=path,
    )
