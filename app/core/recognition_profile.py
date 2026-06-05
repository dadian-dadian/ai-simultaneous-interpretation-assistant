from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RecognitionMode = Literal["low-latency", "balanced", "high-accuracy"]

DEFAULT_RECOGNITION_MODE: RecognitionMode = "balanced"


@dataclass(frozen=True)
class RecognitionProfile:
    mode: RecognitionMode
    label: str
    min_silence_ms: int
    preroll_seconds: float
    queue_size: int
    dropped_chunks_warn_threshold: int = 8

    @property
    def latency_hint(self) -> str:
        hints = {
            "low-latency": "延迟目标 1.2s",
            "balanced": "延迟目标 1.5s",
            "high-accuracy": "延迟目标 2.0s",
        }
        return hints[self.mode]


RECOGNITION_PROFILES: dict[RecognitionMode, RecognitionProfile] = {
    "low-latency": RecognitionProfile(
        mode="low-latency",
        label="低延迟",
        min_silence_ms=500,
        preroll_seconds=0.6,
        queue_size=32,
    ),
    "balanced": RecognitionProfile(
        mode="balanced",
        label="均衡",
        min_silence_ms=800,
        preroll_seconds=0.8,
        queue_size=32,
    ),
    "high-accuracy": RecognitionProfile(
        mode="high-accuracy",
        label="高准确",
        min_silence_ms=1100,
        preroll_seconds=1.0,
        queue_size=64,
    ),
}


def get_recognition_profile(mode: str) -> RecognitionProfile:
    normalized = mode.strip().lower().replace("_", "-")
    aliases = {
        "low": "low-latency",
        "latency": "low-latency",
        "fast": "low-latency",
        "default": "balanced",
        "balance": "balanced",
        "accurate": "high-accuracy",
        "accuracy": "high-accuracy",
        "high": "high-accuracy",
    }
    resolved = aliases.get(normalized, normalized)
    profile = RECOGNITION_PROFILES.get(resolved)  # type: ignore[arg-type]
    if profile is None:
        supported = "、".join(profile.label for profile in RECOGNITION_PROFILES.values())
        raise ValueError(f"不支持的识别模式：{mode}。可选：{supported}")
    return profile


def recognition_mode_from_index(index: int) -> RecognitionMode:
    modes: tuple[RecognitionMode, ...] = ("low-latency", "balanced", "high-accuracy")
    if 0 <= index < len(modes):
        return modes[index]
    return DEFAULT_RECOGNITION_MODE
