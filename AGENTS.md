# SAWPro to Cubase (`sawpro_to_cubase`)

## Project Mission

Reverse-engineer legacy IQS SAWPro / SAW32 binary session files (`.EDL`) using Python on non-Windows environments (macOS / Linux). The primary objective is to extract multi-track timeline event timings, clip placements, and source file references for automated reconstruction in modern DAWs (specifically Steinberg Cubase).

---

## File Format & Architecture Knowledge Base

### 1. File Type Distinctions

- **`.sfk` (Sound Forge Peak Files)**: Pure graphical waveform cache files containing display min/max amplitude peaks. Ignore these—they do not hold timeline or track placement data.
- **`.EDL` (Edit Decision List)**: The proprietary binary project file storing session sample rates, soundfile tables, region cuts, and track placement entries.
- **`.wav`**: Raw audio files referenced by the session.

### 2. Binary Structure Layout

- **Endianness & Packing**: Little-endian (`<`), 1-byte packed C-style structs (`#pragma pack(1)`).
- **Timebase Units**: All timeline positions, region offsets, and clip lengths are stored as absolute sample counts from time zero (`0`), not milliseconds or bar/beat musical grids.

#### Sequential File Sections

- **Header Block (~256–512 bytes)**: Engine magic signature (e.g., `SAW32`, `SAWPRO`), session sample rate (`uint32`: `44100`, `48000`, etc.), SMPTE frame rate flags, active track count, region count, and record counters.
- **Soundfile Table**: Fixed-stride or null-terminated records listing referenced `.wav` files (often with original DOS/Windows drive paths like `C:\SAW\AUDIO\*.WAV`).
- **Region Table**: Sub-clips cut from audio files. Contains Parent Soundfile ID, Sample Start (in-point), Sample End (out-point), and region name.
- **Timeline Event List (MT Entries)**: Array of track placements with a fixed stride (typically 32, 48, or 64 bytes). Typical fields: Track Number ($0$-indexed or $1$-indexed), Sample Start Offset on timeline, Region/Soundfile Pointer, and clip duration.

---

## Implementation Roadmap for Agents

### Phase 1: Binary Inspection & Struct Discovery

1. **Automated Probing**: Build automated probing scripts using Python's `struct` module to scan `.EDL` files:
   - Locate session sample rate offset by searching for `struct.pack("<I", 44100)` or `struct.pack("<I", 48000)`.
   - Extract all null-terminated ASCII strings ($\ge 4$ characters) to locate `.wav` filenames and region labels.
   - Identify table boundaries and calculate the exact byte stride of timeline events.

2. **Typed Data Models**: Define typed data models using `dataclasses`:
   - `SawHeader`
   - `SawSoundfile`
   - `SawRegion`
   - `SawTrackEvent`

### Phase 2: Timeline Parsing & Mathematics

1. **Sample Count Computations**: Compute timestamps and durations from raw sample counts:
   $$\text{Time (seconds)} = \frac{\text{sample\_position}}{\text{sample\_rate}}$$
   $$\text{SMPTE Timecode} = \text{samples} \longrightarrow \text{HH:MM:SS:FF}$$

2. **Reference Resolution**: Resolve clip references across entities:
   $$\text{Timeline Event} \longrightarrow \text{Region} \longrightarrow \text{Parent Soundfile}$$

### Phase 3: DAW Interchange & Export Options

Provide multiple export adapters:

- **Option A: Human-Readable / Scriptable CSV**
  - **Columns**: `Track`, `StartTime_Samples`, `StartTime_Seconds`, `Duration_Samples`, `SoundfileName`, `RegionName`
- **Option B: CMX 3600 EDL**
  - Industry-standard text EDL ingestible by timeline utilities.
- **Option C: Steinberg Track Archive XML**
  - Native Cubase XML import format allowing zero-alignment track placement and audio pool mapping in Cubase Pro.
- **Option D: Advanced Authoring Format (AAF)**
  - Cross-DAW open industry standard (Cubase, Pro Tools, Logic Pro, DaVinci Resolve) with sample-accurate clip placement and relative media locators.

> [!NOTE]
> Exporters use portable relative paths by default (relative to the export destination directory), ensuring cross-platform portability. An `--absolute-paths` CLI option is available when absolute path resolution is required.

---

## Technical Constraints & Environment

- **Platform**: Python 3.10+ using pure standard library (`struct`, `pathlib`, `csv`, `xml.etree.ElementTree`, `dataclasses`, `re`, `argparse`).
- **Cross-Platform**: No Wine, 32-bit emulation, or Windows API dependencies.
- **Resilience**: Use defensive sliding-window parsing to accommodate minor header or struct variations across SAWPro versions.