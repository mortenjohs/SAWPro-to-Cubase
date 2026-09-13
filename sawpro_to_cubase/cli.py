from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .exporters import export_aaf, export_cmx3600, export_csv, export_cubase_xml
from .parser import parse_edl


def print_session_info(session) -> None:
    """Print a clean formatted summary of the parsed session."""
    hdr = session.header
    print("=" * 60)
    print(f" SAWPro Session Information: {session.source_path.name if session.source_path else 'Unknown'}")
    print("=" * 60)
    print(f" Magic Signature : {hdr.magic}")
    print(f" Sample Rate     : {hdr.sample_rate} Hz")
    print(f" SMPTE Code      : {hdr.smpte_format}")
    print(f" Active Tracks   : {hdr.active_tracks}")
    print(f" Total Placements: {session.total_events_count}")
    print("-" * 60)

    print(f"Soundfiles ({len(session.soundfiles)}):")
    for sf in session.soundfiles:
        status = "RESOLVED" if sf.resolved_path else "NOT FOUND"
        print(f"  [{sf.id}] {sf.filename} ({status})")
        print(f"      Original: {sf.original_path}")
        if sf.resolved_path:
            dur = sf.total_frames / sf.sample_rate if sf.sample_rate else 0
            print(f"      Local   : {sf.resolved_path} ({sf.channels}ch, {sf.sample_rate}Hz, {dur:.2f}s)")

    print("-" * 60)
    print(f"Regions ({len(session.regions)}):")
    for reg in session.regions:
        sf = session.get_soundfile(reg.soundfile_id)
        sf_name = sf.filename if sf else f"SF#{reg.soundfile_id}"
        print(f"  [{reg.id}] '{reg.name}' -> {sf_name}")
        print(f"      In: {reg.start_sample} samples | Out: {reg.end_sample} samples | Len: {reg.length_samples} samples")

    print("-" * 60)
    print("Multi-Track Timeline Placements:")
    resolved_events = session.get_resolved_events()
    for ev in resolved_events:
        print(
            f"  Track {ev.track_number:02d} | Start: {ev.timeline_start_smpte} ({ev.timeline_start_seconds:7.3f}s) | "
            f"Dur: {ev.timeline_duration_seconds:7.3f}s | Clip: '{ev.region_name}' ({ev.soundfile_name})"
        )
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sawpro-to-cubase",
        description="Reverse-engineer legacy SAWPro / SAW32 EDL binary sessions and export to modern DAWs.",
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to the SAWPro .EDL or .ED0 session file.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save exported files (defaults to current working directory).",
    )
    parser.add_argument(
        "-a",
        "--audio-dir",
        type=Path,
        default=None,
        help="Optional directory containing source .wav audio files.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["all", "csv", "cmx", "cubase", "aaf"],
        default="all",
        help="Target export format (default: 'all').",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="SMPTE frame rate (default: 30.0).",
    )
    parser.add_argument(
        "--drop-frame",
        action="store_true",
        help="Enable drop-frame timecode calculations (for 29.97 fps).",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Display detailed session summary and exit without exporting.",
    )
    parser.add_argument(
        "--absolute-paths",
        action="store_true",
        help="Use absolute paths for audio files instead of relative paths (default: relative paths).",
    )
    parser.add_argument(
        "--embed-audio",
        action="store_true",
        help="Embed raw audio essence in AAF instead of linking external audio files (default: link audio files).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        session = parse_edl(args.input_file, audio_dir=args.audio_dir)
    except Exception as exc:
        print(f"Error parsing session: {exc}", file=sys.stderr)
        return 1

    if args.info:
        print_session_info(session)
        return 0

    out_dir = args.output_dir or Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = args.input_file.stem

    exported_files: list[Path] = []
    use_relative = not args.absolute_paths

    if args.format in ("all", "csv"):
        csv_path = out_dir / f"{base_name}.csv"
        export_csv(session, csv_path, fps=args.fps, drop_frame=args.drop_frame, relative_paths=use_relative)
        exported_files.append(csv_path)

    if args.format in ("all", "cmx"):
        cmx_path = out_dir / f"{base_name}_cmx.edl"
        export_cmx3600(session, cmx_path, fps=args.fps, drop_frame=args.drop_frame, relative_paths=use_relative)
        exported_files.append(cmx_path)

    if args.format in ("all", "cubase"):
        cubase_path = out_dir / f"{base_name}_cubase.xml"
        export_cubase_xml(session, cubase_path, fps=args.fps, drop_frame=args.drop_frame, relative_paths=use_relative)
        exported_files.append(cubase_path)

    if args.format in ("all", "aaf"):
        aaf_path = out_dir / f"{base_name}.aaf"
        try:
            export_aaf(
                session,
                aaf_path,
                fps=args.fps,
                drop_frame=args.drop_frame,
                relative_paths=use_relative,
                embed_audio=args.embed_audio,
            )
            exported_files.append(aaf_path)
        except ImportError as err:
            if args.format == "aaf":
                print(f"Error: {err}", file=sys.stderr)
                return 1
            logging.warning("Skipping AAF export: %s", err)

    print(f"Successfully processed {args.input_file.name}:")
    for exp in exported_files:
        print(f"  -> Exported: {exp}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
