import os
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import SawSession


def export_cubase_xml(
    session: SawSession,
    output_path: Path | str,
    fps: float = 30.0,
    drop_frame: bool = False,
    relative_paths: bool = True,
) -> Path:
    """
    Export session to a Steinberg Cubase / Nuendo Track Archive XML file.

    :param session: Parsed SawSession.
    :param output_path: Destination path for the XML file.
    :param fps: Frame rate for SMPTE timecodes.
    :param drop_frame: Whether drop-frame mode is enabled.
    :param relative_paths: Whether to use relative paths for audio files (default: True).
    :return: Resolved Path of the exported XML file.
    """
    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    root = ET.Element("trackarchive", version="1.1")

    # 1. Setup Block
    setup = ET.SubElement(root, "setup")
    ET.SubElement(setup, "sampleRate").text = str(session.header.sample_rate)
    ET.SubElement(setup, "frameRate").text = str(fps)
    ET.SubElement(setup, "dropFrame").text = "true" if drop_frame else "false"
    if session.source_path:
        ET.SubElement(setup, "sourceProject").text = session.source_path.name

    # 2. Audio Pool Block
    pool = ET.SubElement(root, "mediapool")
    for sf in session.soundfiles:
        audio_node = ET.SubElement(
            pool,
            "audio",
            id=str(sf.id),
            name=sf.filename,
        )
        ET.SubElement(audio_node, "originalPath").text = sf.original_path
        if sf.resolved_path:
            if relative_paths:
                try:
                    rel_p = os.path.relpath(sf.resolved_path, dest.parent).replace("\\", "/")
                except ValueError:
                    rel_p = str(sf.resolved_path).replace("\\", "/")
                ET.SubElement(audio_node, "resolvedPath").text = rel_p
            else:
                ET.SubElement(audio_node, "resolvedPath").text = str(sf.resolved_path)
        ET.SubElement(audio_node, "sampleRate").text = str(sf.sample_rate)
        ET.SubElement(audio_node, "channels").text = str(sf.channels)
        ET.SubElement(audio_node, "totalFrames").text = str(sf.total_frames)

    # 3. Tracks Block
    tracks_node = ET.SubElement(root, "tracks")

    for track_num in sorted(session.tracks.keys()):
        events = session.tracks[track_num]
        track_elem = ET.SubElement(
            tracks_node,
            "track",
            id=str(track_num),
            name=f"Track {track_num:02d}",
            type="audio",
        )
        events_elem = ET.SubElement(track_elem, "events")

        for ev_idx, ev in enumerate(events):
            reg = session.get_region(ev.region_id)
            reg_name = reg.name if reg else f"Region #{ev.region_id}"
            sf_id = reg.soundfile_id if reg else -1
            sf = session.get_soundfile(sf_id) if reg else None
            sf_name = sf.filename if sf else ""

            src_in = reg.start_sample if reg else 0
            src_out = reg.end_sample if reg else ev.duration_samples

            event_elem = ET.SubElement(
                events_elem,
                "event",
                id=str(ev_idx + 1),
                name=reg_name,
                type="audio",
            )
            # Sample-accurate attributes
            event_elem.set("startSamples", str(ev.start_sample))
            event_elem.set("endSamples", str(ev.end_sample))
            event_elem.set("lengthSamples", str(ev.duration_samples))
            event_elem.set("sourceInSamples", str(src_in))
            event_elem.set("sourceOutSamples", str(src_out))
            event_elem.set("fileId", str(sf_id))
            event_elem.set("soundfileName", sf_name)

            # Human-readable seconds and timecode sub-elements
            ET.SubElement(event_elem, "startSeconds").text = f"{ev.start_sample / session.header.sample_rate:.6f}"
            ET.SubElement(event_elem, "lengthSeconds").text = f"{ev.duration_samples / session.header.sample_rate:.6f}"

    # Pretty-print formatting
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(str(dest), encoding="utf-8", xml_declaration=True)

    return dest
