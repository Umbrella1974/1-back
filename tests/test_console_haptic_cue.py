from __future__ import annotations

from types import SimpleNamespace

from run_pinch_haptic_1back import (
    HapticFeedbackDisplayConfig,
    _print_haptic_feedback_if_needed,
)


def test_console_mode_prints_haptic_event() -> None:
    lines: list[str] = []

    _print_haptic_feedback_if_needed(
        SimpleNamespace(
            haptic_trial_index=0,
            event_name="slip_1",
            modality="vibration",
            duration_ms=800,
            channel_list=(),
        ),
        HapticFeedbackDisplayConfig(mode="console", print_on_emit=True),
        print_fn=lines.append,
    )

    assert lines == [
        "[HAPTIC] trial=0 event=slip_1 modality=vibration duration=800ms"
    ]


def test_console_mode_prints_matrix_channels_and_release_end() -> None:
    lines: list[str] = []

    _print_haptic_feedback_if_needed(
        SimpleNamespace(
            haptic_trial_index=0,
            event_name="left_1",
            modality="matrix",
            duration_ms=500,
            channel_list=(1, 2, 3),
        ),
        HapticFeedbackDisplayConfig(mode="console", print_on_emit=True),
        print_fn=lines.append,
    )
    _print_haptic_feedback_if_needed(
        SimpleNamespace(
            haptic_trial_index=0,
            event_name="release",
            modality="vibration",
            duration_ms=150,
            channel_list=(),
        ),
        HapticFeedbackDisplayConfig(mode="console", print_on_emit=True),
        print_fn=lines.append,
    )

    assert lines == [
        "[HAPTIC] trial=0 event=left_1 modality=matrix channels=[1, 2, 3]",
        "[HAPTIC] trial=0 event=release modality=vibration duration=150ms",
        "[HAPTIC] release emitted; ending dual-task session.",
    ]


def test_none_mode_does_not_print() -> None:
    lines: list[str] = []

    _print_haptic_feedback_if_needed(
        SimpleNamespace(
            haptic_trial_index=0,
            event_name="contact",
            modality="vibration",
            duration_ms=150,
            channel_list=(),
        ),
        HapticFeedbackDisplayConfig(mode="none", print_on_emit=True),
        print_fn=lines.append,
    )

    assert lines == []
