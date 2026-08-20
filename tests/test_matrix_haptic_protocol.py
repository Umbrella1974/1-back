from __future__ import annotations

import pytest

from vendor_exp2_abc.matrix_haptic_protocol import (
    MATRIX_CONTROL_HOLD,
    MATRIX_CONTROL_OFF,
    MATRIX_MAX_AUTO_OFF_MS,
    MATRIX_DURATION_UNIT_MS,
    duration_ms_to_duration_code,
    encode_matrix_auto_off_packet,
    encode_matrix_channel_packet,
    encode_matrix_hold_packet,
    encode_matrix_off_packet,
    encode_matrix_packet,
)


def test_duration_code_is_ms_divided_by_unit() -> None:
    assert duration_ms_to_duration_code(50) == 1
    assert duration_ms_to_duration_code(650) == 13
    assert duration_ms_to_duration_code(MATRIX_MAX_AUTO_OFF_MS) == 31


@pytest.mark.parametrize("duration_ms", [0, -50, 30, 1600])
def test_duration_code_rejects_invalid_durations(duration_ms: int) -> None:
    with pytest.raises(ValueError):
        duration_ms_to_duration_code(duration_ms)


def test_hold_packet_uses_hold_control_byte_and_channels() -> None:
    packet = encode_matrix_hold_packet([82, 84, 87])
    # control 0xE0, channels 0x52 0x54 0x57, checksum 0xDD.
    assert packet == bytes.fromhex("aa 55 aa 55 04 e0 52 54 57 dd")


def test_auto_off_packet_encodes_duration_code_in_low_5_bits() -> None:
    # 650 ms -> code 13 -> 0xE0 | 13 == 0xED.
    packet = encode_matrix_auto_off_packet([82, 84, 87], 650)
    assert packet == bytes.fromhex("aa 55 aa 55 04 ed 52 54 57 ea")


def test_off_packet_is_control_frame_without_enable_or_latch() -> None:
    assert encode_matrix_off_packet() == bytes.fromhex("aa 55 aa 55 01 80 80")


def test_legacy_channel_packet_has_no_control_byte() -> None:
    assert encode_matrix_channel_packet([1, 2, 3]) == bytes.fromhex(
        "aa 55 aa 55 03 01 02 03 06"
    )


def test_hold_and_off_control_byte_constants_are_distinct() -> None:
    assert MATRIX_CONTROL_HOLD == 0xE0
    assert MATRIX_CONTROL_OFF == 0x80


def test_packet_rejects_payload_over_128_bytes() -> None:
    with pytest.raises(ValueError):
        encode_matrix_packet(bytes(129))
