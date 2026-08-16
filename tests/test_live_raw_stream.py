from __future__ import annotations

import time

from vendor_exp2_abc.live_raw_stream import LiveRawFrame, LiveRawStreamServer


def _frame(index: int) -> LiveRawFrame:
    return LiveRawFrame(
        frame_index=index,
        raw_frame={"frame": index},
        receive_time_monotonic=time.monotonic(),
        receive_wall_time=time.time(),
        byte_length=10,
    )


def test_live_raw_stream_drain_frames_clears_queue() -> None:
    server = LiveRawStreamServer(port=0, max_queue_size=3)
    server._enqueue_frame(_frame(1))
    server._enqueue_frame(_frame(2))

    drained = server.drain_frames()

    assert [frame.frame_index for frame in drained] == [1, 2]
    assert server.queue_size() == 0
    assert server.stats_snapshot().total_received_frames == 0
