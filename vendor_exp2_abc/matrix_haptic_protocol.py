"""Matrix electrotactile TCP packet encoding."""

from __future__ import annotations

from typing import Iterable


MATRIX_MAGIC = b"\xAA\x55\xAA\x55"
MATRIX_MAX_PAYLOAD_BYTES = 128
MATRIX_CHANNEL_MIN = 0
MATRIX_CHANNEL_MAX = 127

# gate_autoff firmware control-byte bit fields.
# payload = [control_byte][channels...] (control frame) or raw [channels...] (legacy).
MATRIX_CONTROL_FRAME_MASK = 0x80
MATRIX_OUTPUT_ENABLE_MASK = 0x40
MATRIX_UPDATE_CHANNELS_MASK = 0x20
MATRIX_DURATION_MASK = 0x1F
MATRIX_DURATION_UNIT_MS = 50
MATRIX_MAX_AUTO_OFF_MS = MATRIX_DURATION_MASK * MATRIX_DURATION_UNIT_MS  # 1550

# 0xE0 = control + enable + latch, duration code 0 -> hold until replaced/off.
MATRIX_CONTROL_HOLD = (
    MATRIX_CONTROL_FRAME_MASK | MATRIX_OUTPUT_ENABLE_MASK | MATRIX_UPDATE_CHANNELS_MASK
)
# 0x80 = control frame with no enable/latch -> blank all channels (gate off).
MATRIX_CONTROL_OFF = MATRIX_CONTROL_FRAME_MASK


def duration_ms_to_duration_code(duration_ms: int) -> int:
    """Validate an auto-off duration and return its 5-bit firmware code.

    The gate_autoff firmware computes ``duration_ms = code * 50`` and treats
    ``code == 0`` as hold-forever, so an explicit auto-off must be a positive
    multiple of 50 ms and at most 1550 ms (code 31).
    """

    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise ValueError("duration_ms must be an integer.")
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive.")
    if duration_ms % MATRIX_DURATION_UNIT_MS != 0:
        raise ValueError(
            f"duration_ms must be a multiple of {MATRIX_DURATION_UNIT_MS} ms."
        )
    if duration_ms > MATRIX_MAX_AUTO_OFF_MS:
        raise ValueError(f"duration_ms must be <= {MATRIX_MAX_AUTO_OFF_MS} ms.")
    return duration_ms // MATRIX_DURATION_UNIT_MS


def encode_matrix_packet(payload: bytes) -> bytes:
    """Encode one Matrix ESP32 packet.

    Packet format:
    MAGIC(4B) + payload_length(1B) + payload(N<=128B) + checksum(1B)
    where checksum is ``sum(payload) & 0xFF``.
    """

    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes.")
    payload_bytes = bytes(payload)
    if len(payload_bytes) > MATRIX_MAX_PAYLOAD_BYTES:
        raise ValueError("matrix payload length must be <= 128 bytes.")
    checksum = sum(payload_bytes) & 0xFF
    return MATRIX_MAGIC + bytes([len(payload_bytes)]) + payload_bytes + bytes([checksum])


def channel_list_to_payload(channels: Iterable[int]) -> bytes:
    """Validate and encode an HV507 channel list as payload bytes."""

    payload = bytearray()
    for channel in channels:
        if not isinstance(channel, int):
            raise ValueError(f"matrix channel must be an integer: {channel!r}")
        if channel < MATRIX_CHANNEL_MIN or channel > MATRIX_CHANNEL_MAX:
            raise ValueError(
                f"matrix channel must be in 0..127, got {channel!r}."
            )
        payload.append(channel)
    return bytes(payload)


def encode_matrix_channel_packet(channels: Iterable[int]) -> bytes:
    """Validate a channel list and encode it as a legacy raw-channel packet.

    Kept for backward compatibility; new callers should use the control-frame
    encoders below, which the gate_autoff firmware understands.
    """

    return encode_matrix_packet(channel_list_to_payload(channels))


def encode_matrix_control_packet(control_byte: int, channels: Iterable[int]) -> bytes:
    """Encode a control-frame packet: ``[control_byte][channels...]``."""

    if not isinstance(control_byte, int) or isinstance(control_byte, bool):
        raise ValueError("control_byte must be an integer.")
    if control_byte < 0 or control_byte > 0xFF:
        raise ValueError("control_byte must be in 0..255.")
    return encode_matrix_packet(bytes([control_byte]) + channel_list_to_payload(channels))


def encode_matrix_hold_packet(channels: Iterable[int]) -> bytes:
    """Turn channels on and hold until replaced or explicitly turned off."""

    return encode_matrix_control_packet(MATRIX_CONTROL_HOLD, channels)


def encode_matrix_auto_off_packet(channels: Iterable[int], duration_ms: int) -> bytes:
    """Turn channels on and auto-off after ``duration_ms`` (multiple of 50, <= 1550)."""

    code = duration_ms_to_duration_code(duration_ms)
    return encode_matrix_control_packet(MATRIX_CONTROL_HOLD | code, channels)


def encode_matrix_off_packet() -> bytes:
    """Turn the matrix output off (blank all channels)."""

    return encode_matrix_packet(bytes([MATRIX_CONTROL_OFF]))
