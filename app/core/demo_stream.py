from __future__ import annotations

from dataclasses import dataclass

from app.core.subtitle import SubtitleEvent, SubtitleEventType


@dataclass(frozen=True)
class DemoSubtitleStep:
    delay_ms: int
    event: SubtitleEvent


class DemoSubtitleScript:
    def __init__(self, steps: list[DemoSubtitleStep]) -> None:
        if not steps:
            raise ValueError("Demo subtitle script must contain at least one step")
        self.steps = steps

    def __len__(self) -> int:
        return len(self.steps)

    def __getitem__(self, index: int) -> DemoSubtitleStep:
        return self.steps[index]

    def contains_update(self) -> bool:
        return any(step.event.type == SubtitleEventType.UPDATE for step in self.steps)


def build_default_demo_script() -> DemoSubtitleScript:
    return DemoSubtitleScript(
        steps=[
            DemoSubtitleStep(
                delay_ms=350,
                event=SubtitleEvent.partial(
                    "seg_001",
                    "Today we are going to talk about transformer models",
                    "今天我们将讨论 Transformer 模型……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.final(
                    "seg_001",
                    "Today we are going to talk about transformer models and inference latency.",
                    "今天我们将讨论 Transformer 模型与推理延迟。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=850,
                event=SubtitleEvent.partial(
                    "seg_002",
                    "I study AI agents",
                    "我研究 AI 代理……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=850,
                event=SubtitleEvent.final(
                    "seg_002",
                    "I study AI agents.",
                    "我研究 AI 代理。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=1000,
                event=SubtitleEvent.partial(
                    "seg_003",
                    "They can use tools and complete tasks automatically",
                    "它们可以使用工具并自动完成任务……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.update(
                    "seg_002",
                    "I study AI agents.",
                    "我研究 AI 智能体。",
                    reason="terminology_consistency",
                    old_zh_text="我研究 AI 代理。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=850,
                event=SubtitleEvent.final(
                    "seg_003",
                    "They can use tools and complete tasks automatically.",
                    "它们可以使用工具并自动完成任务。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.partial(
                    "seg_004",
                    "The key challenge is reducing latency without losing context",
                    "关键挑战是在不丢失上下文的情况下降低延迟……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.final(
                    "seg_004",
                    "The key challenge is reducing latency without losing context.",
                    "关键挑战是在不丢失上下文的情况下降低延迟。",
                ),
            ),
        ]
    )

