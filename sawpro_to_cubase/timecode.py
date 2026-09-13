from __future__ import annotations

import math
import re


def samples_to_seconds(samples: int, sample_rate: int) -> float:
    """Convert sample count to seconds."""
    if sample_rate <= 0:
        return 0.0
    return float(samples) / float(sample_rate)


def seconds_to_samples(seconds: float, sample_rate: int) -> int:
    """Convert seconds to sample count."""
    if sample_rate <= 0:
        return 0
    return int(round(seconds * sample_rate))


def samples_to_smpte(
    samples: int,
    sample_rate: int,
    fps: float = 30.0,
    drop_frame: bool = False,
) -> str:
    """Convert sample count to SMPTE timecode string (HH:MM:SS:FF or HH:MM:SS;FF)."""
    if sample_rate <= 0 or samples < 0:
        return "00:00:00:00"

    total_seconds = samples_to_seconds(samples, sample_rate)

    if drop_frame and math.isclose(fps, 29.97, rel_tol=1e-3):
        # SMPTE drop-frame calculation (NTSC 29.97 fps)
        total_frames = int(round(total_seconds * 29.97))
        # 108,000 frames per hour (nominal 30fps) - 108 frames dropped = 107,892 frames/hr
        # 17,982 frames per 10 minutes (18000 - 18)
        # 2 frames dropped at every minute mark except every 10th minute
        d = total_frames // 17982
        m = total_frames % 17982
        if m >= 2:
            frame_number = total_frames + 18 * d + 2 * ((m - 2) // 1798)
        else:
            frame_number = total_frames + 18 * d

        ff = frame_number % 30
        ss = (frame_number // 30) % 60
        mm = (frame_number // 1800) % 60
        hh = (frame_number // 108000) % 24
        return f"{hh:02d}:{mm:02d}:{ss:02d};{ff:02d}"

    nominal_fps = int(round(fps))
    total_frames = int(round(total_seconds * fps))
    ff = total_frames % nominal_fps
    total_secs = total_frames // nominal_fps
    ss = total_secs % 60
    mm = (total_secs // 60) % 60
    hh = (total_secs // 3600) % 24

    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def smpte_to_seconds(smpte_str: str, fps: float = 30.0) -> float:
    """Parse SMPTE string (HH:MM:SS:FF or HH:MM:SS;FF) to seconds."""
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2})[:;](\d{2})$", smpte_str.strip())
    if not match:
        raise ValueError(f"Invalid SMPTE timecode format: '{smpte_str}'")

    hh, mm, ss, ff = map(int, match.groups())
    nominal_fps = int(round(fps))
    total_frames = (hh * 3600 + mm * 60 + ss) * nominal_fps + ff
    return total_frames / fps
