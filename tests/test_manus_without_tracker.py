from __future__ import annotations

import pytest

from manus_pinch_input import ManusOnlyPinchInput, ManusPinchInputConfig


def test_combined_json_without_tracker_reads_pinch_distance() -> None:
    raw = {
        "timestamp": 123.5,
        "frame": 42,
        "skeletons": [
            {
                "gloveId": "glove-a",
                "side": "left",
                "nodes": [
                    {"id": 4, "position": [0.0, 0.0, 0.0]},
                    {"id": 14, "position": [0.03, 0.0, 0.0]},
                ],
            }
        ],
    }
    parser = ManusOnlyPinchInput(
        ManusPinchInputConfig(thumb_node_id=4, target_finger_node_id=14)
    )

    sample = parser.parse_sample(raw, session_id="session-a", wall_time=0.0, monotonic_ms=99.0)

    assert sample.session_id == "session-a"
    assert sample.frame_index == 42
    assert sample.source_frame_id == 42
    assert sample.hand_valid is True
    assert sample.pinch_valid is True
    assert sample.tracker_present is False
    assert sample.pinch_distance == pytest.approx(0.03)
    assert sample.thumb_node_id == 4
    assert sample.target_finger_node_id == 14
    assert sample.thumb_position == [0.0, 0.0, 0.0]
    assert sample.target_finger_position == [0.03, 0.0, 0.0]
    assert sample.note == ""


def test_missing_target_node_returns_invalid_without_crashing() -> None:
    raw = {
        "timestamp": 1.0,
        "frame": 1,
        "skeletons": [
            {
                "nodes": [
                    {"id": 4, "position": [0.0, 0.0, 0.0]},
                ]
            }
        ],
    }

    sample = ManusOnlyPinchInput().parse_sample(raw, wall_time=0.0, monotonic_ms=1.0)

    assert sample.hand_valid is True
    assert sample.pinch_valid is False
    assert sample.pinch_distance is None
    assert "missing_pinch_nodes" in sample.note


def test_require_tracker_marks_sample_invalid_when_tracker_missing() -> None:
    raw = {
        "frame": 2,
        "skeletons": [
            {
                "nodes": [
                    {"id": 4, "position": [0.0, 0.0, 0.0]},
                    {"id": 14, "position": [0.02, 0.0, 0.0]},
                ]
            }
        ],
    }
    parser = ManusOnlyPinchInput(ManusPinchInputConfig(require_tracker=True))

    sample = parser.parse_sample(raw, wall_time=0.0, monotonic_ms=1.0)

    assert sample.pinch_valid is False
    assert sample.pinch_distance is None
    assert "tracker_required_missing" in sample.note

