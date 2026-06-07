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
                    "Good morning everyone and thank you for joining us",
                    "大家早上好，感谢各位参加今天的分享……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.final(
                    "seg_001",
                    "Good morning everyone, and thank you for joining us today.",
                    "大家早上好，感谢各位参加今天的分享。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=850,
                event=SubtitleEvent.partial(
                    "seg_002",
                    "We will begin with the progress from this quarter",
                    "我们先回顾本季度的工作进展……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=850,
                event=SubtitleEvent.final(
                    "seg_002",
                    "We will begin with the progress from this quarter.",
                    "我们先回顾本季度的工作进展。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=1000,
                event=SubtitleEvent.partial(
                    "seg_003",
                    "Then we will look at the priorities for the coming month",
                    "接下来，我们会介绍下个月的重点安排……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.update(
                    "seg_002",
                    "We will begin with the progress from this quarter.",
                    "首先，我们回顾本季度的工作进展。",
                    reason="context_correction",
                    old_zh_text="我们先回顾本季度的工作进展。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=850,
                event=SubtitleEvent.final(
                    "seg_003",
                    "Then we will look at the priorities for the coming month.",
                    "接下来，我们会介绍下个月的重点安排。",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.partial(
                    "seg_004",
                    "Please save your questions until the discussion at the end",
                    "请将问题留到最后的交流环节……",
                ),
            ),
            DemoSubtitleStep(
                delay_ms=900,
                event=SubtitleEvent.final(
                    "seg_004",
                    "Please save your questions until the discussion at the end.",
                    "请将问题留到最后的交流环节。",
                ),
            ),
        ]
    )

