# SAWPro to Cubase (`sawpro_to_cubase`)

## Project Mission

Reverse-engineer legacy IQS SAWPro / SAWPLUS32 / SAW32 binary session files (`.EDL` and `.ED0`) using Python on non-Windows environments (macOS / Linux). The primary objective is to extract multi-track timeline event timings, clip placements, mute/solo states, and source file references for automated reconstruction in modern DAWs (specifically Steinberg Cubase Pro, as well as Pro Tools, Logic Pro, and DaVinci Resolve) and provide an interactive in-browser multi-track preview and mixdown tool.

---

## File Format & Architecture Knowledge Base

### 1. File Type Distinctions

- **`.sfk` (Sound Forge Peak Files)**: Pure graphical waveform cache files containing display min/max amplitude peaks. Ignore these—they do not hold timeline or track placement data.
- **`.EDL` & `.ED0` (Edit Decision Lists & Auto-Backups)**: Proprietary binary session files storing session sample rates, soundfile tables, region cuts, track placement entries, and mixer state. `.ED0` files are automatic backups written by SAW with the exact same binary layout.
- **`.wav`**: Raw PCM audio files referenced by the session.

### 2. Binary Structure Layout & Chunk Architecture

- **Endianness & Packing**: Little-endian (`<`), 1-byte packed C-style structs (`#pragma pack(1)`).
- **Timebase Units**: All timeline positions, region in/out cuts, and clip durations are stored as absolute sample counts from time zero (`0`), not milliseconds or musical bars/beats.

#### Chunk Tags & FourCC Identification

The session file uses structured 8-byte chunk tags followed by 4-byte record counts and 4-byte stride sizes:
`[8-byte Tag ASCII] [4-byte Count: uint32] [4-byte Stride: uint32] [Records Payload]`

1. **Header & Magic Signature (Offset 0–64)**:
   - Magic ASCII string at offset 0 (e.g., `SAWPLUS32 EDL`, `SAW32`, `SAWPRO`).
   - Sample rate: located via `SRATE` tag (with `uint32` value at offset +8) or fallback scan for standard rates (`44100`, `48000`, `88200`, `96000`).
   - SMPTE timecode format code located via `SMPTE` tag.
2. **Soundfile Table (`FILES` Chunk)**:
   - Contains null-terminated strings with original Windows/DOS paths (e.g., `F:\Kunst\Lyd\vals1\Git1.wav`).
   - Unused or deleted slots begin with sentinel `0xFFFFFFFF`.
3. **Region Table (`REGIONS` Chunk)**:
   - Stride contains sub-clip definitions cut from audio files.
   - Bytes 4..68: Region label (null-padded Latin-1 / ASCII).
   - Offset 104: In-point / start sample (`uint32`).
   - Offset 108: Out-point / stop sample (`uint32`).
   - Offset 112: Soundfile ID index (`uint32`).
   - Sentinel `0xFFFFFFFF` at start indicates an inactive or deleted region slot.
4. **Track Placements (`TRACK01` to `TRACKxx` Chunks)**:
   - Each active track has its own chunk named `TRACK01\0`, `TRACK02\0`, etc.
   - Count indicates number of event records; stride is 48 bytes.
   - First 12 bytes of each 48-byte record:
     - Offset 0: Region ID (`uint32`).
     - Offset 4: Timeline Start Sample (`uint32`).
     - Offset 8: Timeline End Sample (`uint32`).
     - Duration = `End - Start`.
   - Sentinel `0xFFFFFFFF` indicates inactive entry.
5. **Mixer Mute & Solo States (`MUTE` and `SOLO` Chunks)**:
   - Located via `MUTE\0` and `SOLO\0` tags.
   - Followed by array of 44 `uint32` values corresponding to tracks 1..44.
   - Non-zero values represent active mute or solo states from the original project.

---

## Audio Resolution Engine (4-Pass Pipeline)

Legacy sessions frequently contain Windows/DOS path separators (`\`), uppercase extensions, and cross-platform character-encoding mismatches from vintage Norwegian/European DOS or Windows codepages. The parser implements a multi-pass resolver:

1. **Pass 1: Direct Exact Match**: Checks exact filename in candidate project directories.
2. **Pass 2: Case-Insensitive Match**: Matches lowercase variants (e.g., `GIT1.WAV` -> `Git1.wav`).
3. **Pass 3: Codepage & Transliteration Matrix**:
   - Cross-translates characters between Windows ANSI (`cp1252`), DOS OEM (`cp850`, `cp865`, `cp437`), MacRoman, and UTF-8 normalizations (`NFC`, `NFD`, `NFKC`, `NFKD`).
   - Resolves characters such as `æ` <-> `µ` / `‘`, `ø` <-> `°` / `›`, `å` <-> `Õ` / `σ` / `†`.
4. **Pass 4: Skeleton & Audio Length Verification**:
   - Strips non-alphanumeric characters from stem names.
   - Verifies candidate `.wav` header frame count against `min_frames` required by the region cuts, preventing mismatched take files or short preview renders.

---

## DAW Interchange & Export Engine

All exporters are available via CLI and Web UI. They default to portable relative paths (relative to export destination directory):

1. **Advanced Authoring Format (AAF)** (`aaf_exporter.py` via `pyaaf2`):
   - Sample-accurate composition mobility across Cubase Pro, Pro Tools, Logic Pro, and DaVinci Resolve.
   - Dedicated `MasterMob` with multi-track timeline slots, `SourceMob` file descriptors, and Timecode track.
   - Uses relative RFC URIs (`audio/filename.wav`) by default for clean, zero-missing-media import into Cubase Pro.
   - Supports optional `--embed-audio` to write raw PCM audio essence directly inside the AAF container.
2. **Steinberg Track Archive XML** (`cubase_xml_exporter.py`):
   - Native Cubase XML format (`_cubase.xml`) with `PTrackArchiveMediaPool`, `MAudioTrackEvent`, and `MAudioClip`.
   - Imported via *File > Import > Track Archive*.
3. **CMX 3600 EDL** (`cmx_exporter.py`):
   - Standard text-based EDL with source tape in/out and timeline in/out timecodes.
4. **Scriptable CSV** (`csv_exporter.py`):
   - Comprehensive spreadsheet listing tracks, sample counts, seconds, SMPTE timecodes, and file paths.
5. **Bundled Interchange ZIP**:
   - Automatically packages all four export formats into a single zip archive.

---

## Interactive Web Application & Audio Player

- **Server Architecture** (`server.py`): Pure Python standard library (`http.server`), zero external frameworks (no Flask/FastAPI required).
- **In-Browser Multi-Track Web Audio Engine** (`app.js`):
  - Sample-accurate multi-track audio playback using native Web Audio API (`AudioContext`, `AudioBufferSourceNode`, `GainNode`).
  - Animated live playhead scrubber and click-to-seek timeline.
  - Per-track Mute (`M`) and Solo (`S`) controls, initialized automatically from the session's parsed `MUTE` and `SOLO` tables.
  - Full transport controls (Play, Pause, Stop, Spacebar toggle, volume/mute).
  - Client-side audio decoding when files are dropped in browser; server streaming fallback (`/api/audio`).
  - Full Safari / WebKit audio autoplay resilience (user-gesture audio unlocks, dedicated node routing).
- **Mixdown Audio Export**:
  - Exports the audible mix directly to **WAV** or **MP3** (using client-side `OfflineAudioContext` + `lamejs` or server mixdown).
  - Honors active track mute and solo states.

---

## Technical Constraints & Guidelines for Agents

- **Platform**: Python 3.10+ using pure standard library (`struct`, `pathlib`, `csv`, `xml.etree.ElementTree`, `dataclasses`, `re`, `argparse`, `http.server`, `wave`) + `pyaaf2`.
- **Zero OS Emulation**: No Wine, 32-bit binaries, or Windows API dependencies.
- **Defensive Parsing**: Use sliding-window search and chunk tag detection to gracefully handle version differences between SAW32, SAWPLUS32, and SAWPro.
- **Preserve Relative Paths**: Keep exports relative to the output directory so project folders remain portable across systems.