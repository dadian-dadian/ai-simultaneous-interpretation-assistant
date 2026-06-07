import unittest

from app.asr.baidu import BaiduRealtimeTranscript
from app.asr.types import AsrResult, AsrTextSegment
from app.core.asr_sentence import AsrSentenceMapper
from app.core.subtitle import SubtitleEventType, SubtitleState


class AsrSentenceMapperTest(unittest.TestCase):
    def test_partial_and_final_share_a_sentence_id_then_advance(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")

        partial_events = mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="I love", is_final=False)]
        )
        final_events = mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="I love that job.",
                    is_final=True,
                    start_seconds=0.0,
                    end_seconds=1.2,
                )
            ]
        )
        next_events = mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="And then", is_final=False)]
        )

        self.assertEqual(partial_events[0].segment_id, "asr_0001_s0001")
        self.assertEqual(final_events[0].segment_id, "asr_0001_s0001")
        self.assertEqual(next_events[0].segment_id, "asr_0001_s0002")
        self.assertEqual(final_events[0].type, SubtitleEventType.FINAL)

    def test_single_word_partial_is_delayed_until_it_has_context(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")

        first_events = mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="and", is_final=False)]
        )
        second_events = mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="and I", is_final=False)]
        )

        self.assertEqual(first_events, [])
        self.assertEqual(second_events[0].source_text, "and I")

    def test_finish_result_emits_unseen_final_segments_individually(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")
        result = AsrResult(
            text="First sentence. Second sentence.",
            language="en",
            provider="fake",
            duration_seconds=2.0,
            segments=(
                AsrTextSegment("First sentence.", 0.0, 1.0),
                AsrTextSegment("Second sentence.", 1.0, 2.0),
            ),
        )

        events = mapper.accept_finish_result(result)

        self.assertEqual(
            [event.segment_id for event in events],
            ["asr_0001_s0001", "asr_0001_s0002"],
        )
        self.assertEqual(events[1].source_text, "Second sentence.")

    def test_final_transcript_keeps_provider_fin_as_one_unit(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")

        events = mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="First sentence. Second sentence.",
                    is_final=True,
                    start_seconds=0.0,
                    end_seconds=2.0,
                )
            ]
        )

        self.assertEqual(
            [(event.segment_id, event.source_text) for event in events],
            [
                ("asr_0001_s0001", "First sentence. Second sentence."),
            ],
        )

    def test_final_transcript_normalizes_missing_space_without_splitting(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")

        events = mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="The display ended.This should be a new sentence.",
                    is_final=True,
                )
            ]
        )

        self.assertEqual(
            [event.source_text for event in events],
            ["The display ended. This should be a new sentence."],
        )

    def test_finish_result_does_not_duplicate_streamed_final(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")
        mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="Already final.",
                    start_seconds=0.0,
                    end_seconds=1.0,
                    is_final=True,
                )
            ]
        )
        result = AsrResult(
            text="Already final.",
            language="en",
            provider="fake",
            duration_seconds=1.0,
            segments=(AsrTextSegment("Already final.", 0.0, 1.0),),
        )

        self.assertEqual(mapper.accept_finish_result(result), [])

    def test_fallback_finalizes_current_visible_partial(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")
        mapper.accept_transcripts([BaiduRealtimeTranscript(text="because what", is_final=False)])

        events = mapper.accept_finish_result(None, fallback_text="because what happened")

        self.assertEqual(events[0].segment_id, "asr_0001_s0001")
        self.assertEqual(events[0].source_text, "because what happened")

    def test_stream_finish_can_require_real_provider_fin_segments(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")
        mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="still only a draft", is_final=False)]
        )
        result = AsrResult(
            text="still only a draft",
            language="en",
            provider="baidu-realtime",
            duration_seconds=1.0,
        )

        events = mapper.accept_finish_result(
            result,
            allow_result_text_fallback=False,
        )

        self.assertEqual(events, [])

    def test_sentence_ids_are_safe_for_translation_versioning(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")
        state = SubtitleState()

        for event in mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="I love", is_final=False)]
        ):
            state.apply(event)
        for event in mapper.accept_transcripts(
            [BaiduRealtimeTranscript(text="I love that job.", is_final=True)]
        ):
            segment = state.apply(event)

        self.assertEqual(segment.segment_id, "asr_0001_s0001")
        self.assertEqual(segment.version, 2)

    def test_late_mid_for_finalized_provider_sentence_is_ignored(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")

        events = mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="I love",
                    is_final=False,
                    sentence_id="provider_0",
                ),
                BaiduRealtimeTranscript(
                    text="I love that job.",
                    is_final=True,
                    sentence_id="provider_0",
                ),
                BaiduRealtimeTranscript(
                    text="I love that job with a late revision",
                    is_final=False,
                    sentence_id="provider_0",
                ),
            ]
        )

        self.assertEqual(
            [(event.type, event.segment_id, event.source_text) for event in events],
            [
                (SubtitleEventType.PARTIAL, "asr_0001_s0001", "I love"),
                (SubtitleEventType.FINAL, "asr_0001_s0001", "I love that job."),
            ],
        )

    def test_weak_final_boundary_is_merged_with_next_provider_sentence(self) -> None:
        mapper = AsrSentenceMapper("asr_0001")

        first_events = mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="This is true whether you are in",
                    is_final=True,
                    sentence_id="provider_0",
                )
            ]
        )
        second_events = mapper.accept_transcripts(
            [
                BaiduRealtimeTranscript(
                    text="stocks or venture capital politics or nonprofit",
                    is_final=False,
                    sentence_id="provider_1",
                )
            ]
        )

        self.assertEqual(first_events[0].type, SubtitleEventType.PARTIAL)
        self.assertEqual(first_events[0].segment_id, "asr_0001_s0001")
        self.assertEqual(
            second_events[0].source_text,
            (
                "This is true whether you are in stocks or venture capital "
                "politics or nonprofit"
            ),
        )
        self.assertEqual(second_events[0].segment_id, "asr_0001_s0001")


if __name__ == "__main__":
    unittest.main()
