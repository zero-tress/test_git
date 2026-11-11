"""Small sampling records; no dependency on the colleague graph/model stack."""
from dataclasses import asdict, dataclass, field, replace


@dataclass
class FrameReference:
    frame_id: str
    path: str
    timestamp: float
    selection_score: float = 0.0
    selection_roles: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    selection_reasons: list[str] = field(default_factory=list)

    def model_dump(self, **kwargs):
        return asdict(self)

    def model_copy(self, *, update):
        return replace(self, **update)


@dataclass
class VideoWindow:
    window_id: str
    start_time: float
    end_time: float
    frames: list[FrameReference] = field(default_factory=list)
