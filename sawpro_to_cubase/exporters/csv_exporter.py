import csv
import os
from pathlib import Path

from ..models import SawSession


def export_csv(
    session: SawSession,
    output_path: Path | str,
    fps: float = 30.0,
    drop_frame: bool = False,
    relative_paths: bool = True,
) -> Path:
    """
    Export session timeline events to a CSV file.

    :param session: Parsed SawSession.
    :param output_path: Destination path for the CSV.
    :param fps: Frame rate for SMPTE timecodes.
    :param drop_frame: Whether to format SMPTE as drop-frame.
    :param relative_paths: Whether to use relative paths for audio files (default: True).
    :return: Resolved Path of the exported CSV file.
    """
    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "Track",
        "StartTime_Samples",
        "StartTime_Seconds",
        "Duration_Samples",
        "Duration_Seconds",
        "StartTime_SMPTE",
        "EndTime_SMPTE",
        "SoundfileName",
        "RegionName",
        "SourceIn_Samples",
        "SourceOut_Samples",
        "AudioFilePath",
    ]

    events = session.get_resolved_events(fps=fps, drop_frame=drop_frame)

    with open(dest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ev in events:
            if ev.audio_file_path:
                if relative_paths:
                    try:
                        audio_p = os.path.relpath(ev.audio_file_path, dest.parent).replace("\\", "/")
                    except ValueError:
                        audio_p = str(ev.audio_file_path).replace("\\", "/")
                else:
                    audio_p = str(ev.audio_file_path)
            else:
                audio_p = ""

            writer.writerow(
                {
                    "Track": ev.track_number,
                    "StartTime_Samples": ev.timeline_start_samples,
                    "StartTime_Seconds": f"{ev.timeline_start_seconds:.6f}",
                    "Duration_Samples": ev.timeline_duration_samples,
                    "Duration_Seconds": f"{ev.timeline_duration_seconds:.6f}",
                    "StartTime_SMPTE": ev.timeline_start_smpte,
                    "EndTime_SMPTE": ev.timeline_end_smpte,
                    "SoundfileName": ev.soundfile_name,
                    "RegionName": ev.region_name,
                    "SourceIn_Samples": ev.source_in_samples,
                    "SourceOut_Samples": ev.source_out_samples,
                    "AudioFilePath": audio_p,
                }
            )

    return dest
