from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SawHeader:
    """Header information from the SAWPro/SAW32 EDL file."""
    magic: str
    sample_rate: int
    smpte_format: int
    active_tracks: int = 0


@dataclass
class SawSoundfile:
    """Referenced audio file in the session."""
    id: int
    original_path: str
    resolved_path: Optional[Path] = None
    filename: str = ""
    sample_rate: int = 0
    channels: int = 0
    total_frames: int = 0

    def __post_init__(self) -> None:
        if not self.filename and self.original_path:
            # Handle Windows/DOS backslashes as well as POSIX slashes
            clean_path = self.original_path.replace("\\", "/")
            self.filename = clean_path.split("/")[-1]


@dataclass
class SawRegion:
    """Audio region (cut/clip definition) referencing a soundfile."""
    id: int
    name: str
    soundfile_id: int
    start_sample: int
    end_sample: int
    length_samples: int = 0

    def __post_init__(self) -> None:
        if self.length_samples == 0 and self.end_sample >= self.start_sample:
            self.length_samples = self.end_sample - self.start_sample


@dataclass
class SawTrackEvent:
    """Timeline placement on an audio track."""
    track_number: int  # 1-indexed track number
    region_id: int
    start_sample: int
    end_sample: int
    duration_samples: int = 0

    def __post_init__(self) -> None:
        if self.duration_samples == 0 and self.end_sample >= self.start_sample:
            self.duration_samples = self.end_sample - self.start_sample


@dataclass
class ResolvedEvent:
    """Fully resolved timeline placement with timing conversions and file metadata."""
    track_number: int
    timeline_start_samples: int
    timeline_end_samples: int
    timeline_duration_samples: int
    timeline_start_seconds: float
    timeline_end_seconds: float
    timeline_duration_seconds: float
    timeline_start_smpte: str
    timeline_end_smpte: str

    source_in_samples: int
    source_out_samples: int
    source_in_seconds: float
    source_out_seconds: float
    source_in_smpte: str
    source_out_smpte: str

    region_id: int
    region_name: str
    soundfile_id: int
    soundfile_name: str
    audio_file_path: Optional[Path] = None


@dataclass
class SawSession:
    """Complete parsed SAWPro session."""
    header: SawHeader
    soundfiles: list[SawSoundfile] = field(default_factory=list)
    regions: list[SawRegion] = field(default_factory=list)
    tracks: dict[int, list[SawTrackEvent]] = field(default_factory=dict)
    source_path: Optional[Path] = None

    def get_soundfile(self, soundfile_id: int) -> Optional[SawSoundfile]:
        for sf in self.soundfiles:
            if sf.id == soundfile_id:
                return sf
        return None

    def get_region(self, region_id: int) -> Optional[SawRegion]:
        for reg in self.regions:
            if reg.id == region_id:
                return reg
        return None

    @property
    def active_track_numbers(self) -> list[int]:
        return sorted(t for t, events in self.tracks.items() if len(events) > 0)

    @property
    def total_events_count(self) -> int:
        return sum(len(events) for events in self.tracks.values())

    def get_resolved_events(self, fps: float = 30.0, drop_frame: bool = False) -> list[ResolvedEvent]:
        from .timecode import samples_to_seconds, samples_to_smpte

        resolved: list[ResolvedEvent] = []
        sr = self.header.sample_rate

        for track_num in sorted(self.tracks.keys()):
            for ev in self.tracks[track_num]:
                reg = self.get_region(ev.region_id)
                reg_name = reg.name if reg else f"Region #{ev.region_id}"
                sf_id = reg.soundfile_id if reg else -1
                sf = self.get_soundfile(sf_id) if reg else None
                sf_name = sf.filename if sf else ""
                audio_path = sf.resolved_path if sf else None

                src_in = reg.start_sample if reg else 0
                src_out = reg.end_sample if reg else ev.duration_samples

                tl_start_sec = samples_to_seconds(ev.start_sample, sr)
                tl_end_sec = samples_to_seconds(ev.end_sample, sr)
                tl_dur_sec = samples_to_seconds(ev.duration_samples, sr)

                src_in_sec = samples_to_seconds(src_in, sr)
                src_out_sec = samples_to_seconds(src_out, sr)

                resolved.append(
                    ResolvedEvent(
                        track_number=track_num,
                        timeline_start_samples=ev.start_sample,
                        timeline_end_samples=ev.end_sample,
                        timeline_duration_samples=ev.duration_samples,
                        timeline_start_seconds=tl_start_sec,
                        timeline_end_seconds=tl_end_sec,
                        timeline_duration_seconds=tl_dur_sec,
                        timeline_start_smpte=samples_to_smpte(ev.start_sample, sr, fps, drop_frame),
                        timeline_end_smpte=samples_to_smpte(ev.end_sample, sr, fps, drop_frame),
                        source_in_samples=src_in,
                        source_out_samples=src_out,
                        source_in_seconds=src_in_sec,
                        source_out_seconds=src_out_sec,
                        source_in_smpte=samples_to_smpte(src_in, sr, fps, drop_frame),
                        source_out_smpte=samples_to_smpte(src_out, sr, fps, drop_frame),
                        region_id=ev.region_id,
                        region_name=reg_name,
                        soundfile_id=sf_id,
                        soundfile_name=sf_name,
                        audio_file_path=audio_path,
                    )
                )

        return resolved
