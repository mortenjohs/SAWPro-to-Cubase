import os
import re
from pathlib import Path

from ..models import SawSession


def _sanitize_reel(name: str, fallback_idx: int) -> str:
    """Sanitize reel name to 8 uppercase alphanumeric characters for CMX 3600."""
    clean = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    if not clean:
        return f"REEL{fallback_idx:03d}"
    return clean[:8]


def export_cmx3600(
    session: SawSession,
    output_path: Path | str,
    fps: float = 30.0,
    drop_frame: bool = False,
    relative_paths: bool = True,
) -> Path:
    """
    Export session events to an industry-standard CMX 3600 text EDL.

    :param session: Parsed SawSession.
    :param output_path: Destination path for the CMX EDL.
    :param fps: Frame rate for SMPTE timecodes.
    :param drop_frame: Whether drop frame mode is enabled.
    :param relative_paths: Whether to use relative paths for audio files (default: True).
    :return: Resolved Path of the exported file.
    """
    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    title = session.source_path.stem if session.source_path else "SAWPRO_SESSION"
    # Ensure title is uppercase and alphanumeric
    clean_title = re.sub(r"[^A-Za-z0-9_]", "_", title.upper())[:32]
    fcm_mode = "DROP FRAME" if drop_frame else "NON-DROP FRAME"

    lines: list[str] = [
        f"TITLE: {clean_title}",
        f"FCM: {fcm_mode}",
        "",
    ]

    events = session.get_resolved_events(fps=fps, drop_frame=drop_frame)

    for idx, ev in enumerate(events, start=1):
        event_num = f"{idx:03d}"
        reel = _sanitize_reel(ev.soundfile_name, idx)
        track_type = f"A{ev.track_number}" if ev.track_number > 1 else "A"
        track_col = f"{track_type:<4}"

        src_in = ev.source_in_smpte
        src_out = ev.source_out_smpte
        dst_in = ev.timeline_start_smpte
        dst_out = ev.timeline_end_smpte

        # Standard CMX edit decision line:
        # 001  REELNAME A    C        00:00:00:00 00:01:48:25 00:00:00:00 00:01:48:25
        lines.append(
            f"{event_num}  {reel:<8} {track_col} C        {src_in} {src_out} {dst_in} {dst_out}"
        )
        # Comments
        if ev.region_name:
            lines.append(f"* FROM CLIP NAME: {ev.region_name}")
        if ev.soundfile_name:
            lines.append(f"* SOURCE FILE: {ev.soundfile_name}")
        if ev.audio_file_path:
            if relative_paths:
                try:
                    audio_p = os.path.relpath(ev.audio_file_path, dest.parent).replace("\\", "/")
                except ValueError:
                    audio_p = str(ev.audio_file_path).replace("\\", "/")
            else:
                audio_p = str(ev.audio_file_path)
            lines.append(f"* AUDIO PATH: {audio_p}")
        lines.append("")

    dest.write_text("\r\n".join(lines) + "\r\n", encoding="ascii", errors="replace")
    return dest
