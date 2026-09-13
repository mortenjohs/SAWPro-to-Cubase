from __future__ import annotations

import logging
import os
from pathlib import Path

from ..models import SawSession

logger = logging.getLogger(__name__)


def export_aaf(
    session: SawSession,
    output_path: Path | str,
    fps: float = 30.0,
    drop_frame: bool = False,
    relative_paths: bool = True,
    embed_audio: bool = False,
) -> Path:
    """
    Export session to an Advanced Authoring Format (AAF) file.

    :param session: Parsed SawSession.
    :param output_path: Destination path for the .aaf file.
    :param fps: Optional video frame rate (tracks use audio sample rate for sample accuracy).
    :param drop_frame: Whether drop-frame mode is enabled.
    :param relative_paths: Whether to reference audio files with relative paths (default: True).
    :param embed_audio: Whether to embed audio essence directly inside the AAF file (default: False).
    :return: Resolved Path of the exported file.
    """
    try:
        import aaf2
        from aaf2.rational import AAFRational
    except ImportError as exc:
        raise ImportError(
            "pyaaf2 is required to export AAF files. Install it using: pip install pyaaf2"
        ) from exc

    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    with aaf2.open(str(dest), "w") as f:
        # 1. CompositionMob (Timeline)
        title = session.source_path.stem if session.source_path else "SAWPRO_SESSION"
        comp_mob = f.create.CompositionMob(title)
        comp_mob.usage = "Usage_TopLevel"
        f.content.mobs.append(comp_mob)

        # 1b. Timecode track (Required by DAWs such as Cubase to prevent NULL pointer dereference)
        if drop_frame:
            tc_edit_rate = AAFRational(30000, 1001)
            tc_fps = 30
            tc_drop = True
        elif abs(fps - 29.97) < 0.01:
            tc_edit_rate = AAFRational(30000, 1001)
            tc_fps = 30
            tc_drop = drop_frame
        else:
            tc_edit_rate = int(round(fps))
            tc_fps = int(round(fps))
            tc_drop = False

        max_sample = 0
        for track_events in session.tracks.values():
            for ev in track_events:
                if ev.end_sample > max_sample:
                    max_sample = ev.end_sample

        dur_sec = max_sample / session.header.sample_rate if session.header.sample_rate else 3600.0
        tc_len = max(1, int(dur_sec * float(tc_edit_rate)) + int(tc_fps) * 10)

        tc_slot = comp_mob.create_timeline_slot(edit_rate=tc_edit_rate)
        tc_slot.name = "Timecode slot"
        tc = f.create.Timecode(fps=tc_fps, drop=tc_drop)
        tc.start = 0
        tc.length = tc_len
        tc_slot.segment = tc

        # 2. MasterMobs for each resolved soundfile
        master_mobs = {}
        master_slots = {}
        for sf in session.soundfiles:
            if not sf.resolved_path or not sf.resolved_path.is_file():
                continue
            mm = f.create.MasterMob(sf.filename)
            f.content.mobs.append(mm)
            # Embed audio essence by default (offline=False embeds raw PCM audio)
            mslot = mm.import_audio_essence(str(sf.resolved_path), offline=not embed_audio)
            master_mobs[sf.id] = mm
            master_slots[sf.id] = mslot

            # Always attach an RFC-compliant NetworkLocator so DAWs (such as Cubase)
            # never fail with AAFRESULT_PROP_NOT_PRESENT (0x801200CF) on GetLocators().
            if relative_paths and not embed_audio:
                try:
                    rel_p = os.path.relpath(sf.resolved_path, dest.parent).replace("\\", "/")
                    uri = f"file:{rel_p}"
                except ValueError:
                    uri = sf.resolved_path.as_uri()
            else:
                uri = sf.resolved_path.as_uri()

            loc = f.create.NetworkLocator()
            loc["URLString"].value = uri
            source_mob = f.content.mobs.get(mslot.segment.mob_id)
            if source_mob and hasattr(source_mob, "descriptor") and source_mob.descriptor:
                source_mob.descriptor["Locator"].append(loc)

        # 3. Track slots on CompositionMob
        edit_rate = session.header.sample_rate
        for track_num in sorted(session.tracks.keys()):
            events = sorted(session.tracks[track_num], key=lambda e: e.start_sample)
            if not events:
                continue

            slot = comp_mob.create_sound_slot(edit_rate=edit_rate)
            slot.name = f"Track {track_num:02d}"

            seq = f.create.Sequence(media_kind="sound")
            slot.segment = seq

            current_sample = 0
            for ev in events:
                reg = session.get_region(ev.region_id)
                sf_id = reg.soundfile_id if reg else -1
                if sf_id not in master_mobs:
                    continue

                # Fill gaps between clips with silent Filler
                if ev.start_sample > current_sample:
                    gap = ev.start_sample - current_sample
                    filler = f.create.Filler(media_kind="sound", length=gap)
                    seq.components.append(filler)
                    current_sample += gap

                src_in = reg.start_sample if reg else 0
                dur = ev.duration_samples
                mm = master_mobs[sf_id]
                mslot = master_slots[sf_id]

                clip = mm.create_source_clip(slot_id=mslot.slot_id, start=src_in, length=dur)
                seq.components.append(clip)
                current_sample += dur

            seq.length = current_sample

    return dest
