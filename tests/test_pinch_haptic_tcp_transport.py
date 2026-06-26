from __future__ import annotations

import json
import socket
import threading

import pytest

from run_pinch_haptic_dry_run import (
    DEFAULT_MANUS_TCP_HOST,
    DEFAULT_MANUS_TCP_PORT,
    ManusTcpLogState,
    _get_manus_frame,
    _log_manus_listening,
    _make_manus_tcp_server,
    _wait_for_manus_client,
)


def test_dry_run_manus_tcp_server_receives_first_newline_json_on_8888(capsys) -> None:
    server = _make_manus_tcp_server(
        {
            "tcp_host": DEFAULT_MANUS_TCP_HOST,
            "tcp_port": DEFAULT_MANUS_TCP_PORT,
        }
    )
    release_client = threading.Event()
    client_errors: list[BaseException] = []
    payload = {"frame": 1, "skeletons": []}

    def fake_client() -> None:
        try:
            with socket.create_connection(
                (DEFAULT_MANUS_TCP_HOST, DEFAULT_MANUS_TCP_PORT),
                timeout=2.0,
            ) as sock:
                sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
                release_client.wait(timeout=1.0)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            client_errors.append(exc)

    try:
        try:
            server.start()
        except OSError as exc:
            pytest.fail(
                "Could not bind MANUS smoke server on 127.0.0.1:8888. "
                "Stop capture_raw_jsonl.py or any other process using 8888 "
                f"before running this transport smoke test. Original error: {exc}"
            )

        state = ManusTcpLogState()
        _log_manus_listening(server)
        client_thread = threading.Thread(target=fake_client, daemon=True)
        client_thread.start()

        assert _wait_for_manus_client(
            server,
            timeout_s=2.0,
            log_state=state,
            poll_s=0.01,
        )
        frame = _get_manus_frame(server, timeout=2.0, log_state=state)

        release_client.set()
        client_thread.join(timeout=1.0)

        assert client_errors == []
        assert frame is not None
        assert frame.raw_frame == payload
        assert frame.frame_index == 0

        output = capsys.readouterr().out
        assert "[MANUS TCP] listening on 127.0.0.1:8888" in output
        assert "[MANUS TCP] client connected" in output
        assert "[MANUS TCP] first frame received" in output
    finally:
        release_client.set()
        server.stop("test_finished")
        server.join(timeout=1.0)
