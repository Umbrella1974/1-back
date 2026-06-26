from __future__ import annotations

from nback_dualtask_runner import (
    NBACK_PHASE_STIMULUS,
    NBackConfig,
    NBackTimeline,
)


def test_nback_timeline_generates_stimulus_onsets() -> None:
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=3,
            fixation_duration_ms=100,
            stimulus_duration_ms=200,
            isi_min_ms=300,
            isi_max_ms=300,
            key_same="left",
            key_different="right",
        ),
        sequence=[1, 1, 2],
        isi_ms=[300, 300, 300],
        wall_time_fn=lambda: 0.0,
    )

    timeline.start(1000.0)

    assert timeline.digit_onsets_ms == [1100.0, 1700.0, 2300.0]
    tick = timeline.tick(1100.0)
    assert tick.phase == NBACK_PHASE_STIMULUS
    assert tick.trial is not None
    assert tick.trial.stimulus == 1
    assert [trial.is_target for trial in timeline.trials] == [False, True, False]


def test_nback_response_records_monotonic_time_and_rt() -> None:
    timeline = NBackTimeline(
        NBackConfig(
            num_trials=2,
            fixation_duration_ms=0,
            stimulus_duration_ms=200,
            isi_min_ms=300,
            isi_max_ms=300,
            key_same="left",
            key_different="right",
        ),
        sequence=[4, 4],
        isi_ms=[300, 300],
        wall_time_fn=lambda: 0.0,
    )
    timeline.start(1000.0)

    response = timeline.record_response("left", 1530.0)
    rows = timeline.finalize_until(2000.0, session_id="nback-session")

    assert response is not None
    assert response.stimulus_index == 1
    assert response.rt_ms == 30.0
    assert response.correct is True
    assert len(rows) == 2
    assert rows[1].response_key == "left"
    assert rows[1].response_monotonic_ms == 1530.0
    assert rows[1].rt_ms == 30.0
    assert rows[1].correct is True
