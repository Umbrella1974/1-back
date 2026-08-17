import uasyncio as asyncio
import usocket as socket
import time

from machine import Pin, SoftI2C
from drv2605 import DRV2605


# =========================================================
# TCP / DRV2605 configuration for 1-back only-motor
# =========================================================

TCP_PORT = 12346
HANDSHAKE_COMMANDS = (
    "PING",
    "HELLO",
)
HANDSHAKE_RESPONSE = "OK PONG"

I2C_SDA = 8
I2C_SCL = 9


# =========================================================
# Fixed Rough Slip configuration
#
# Tacton 11:
# Pattern 33 = Alternating Small-Large
#
# 55  -> 150 ms
# 145 -> 150 ms
# repeat...
#
# 总时长固定 2 秒
# =========================================================

DEFAULT_SLIP_DURATION_MS = 2000

ROUGH_SLIP_MOTIF = [
    (55, 150),
    (145, 150),
]


# =========================================================
# Time helpers
# =========================================================

def ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()

    return int(time.time() * 1000)


def ticks_diff(t1, t0):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(t1, t0)

    return t1 - t0


# =========================================================
# Enabled haptic tactons
# =========================================================

HAPTIC_ICONS = {

    # Icon 1 contact
    1: [
        (18, 0),
    ],

    # Icon 4
    4: [
        (52, 0),
        (52, 0),
    ],

    # Icon 5
    5: [
        (65, 40),
        (65, 40),
        (1, 0),        

    ],

    # Icon 8
    8: [
        (65, 40),
        (1, 0),
    ],

    # Icon 9
    9: [
        (65, 50),
        (1, 50),
        (65, 0),
    ],

    # Icon 10
    10: [
        (1, 50),
        (65, 0),
    ],
}


# 保留原来的 tacton ID 名称
ROUGH_SLIP_TACTON_ID = 11

VALID_TACTON_IDS = (
    1,
    4,
    5,
    8,
    9,
    10,
    ROUGH_SLIP_TACTON_ID,
)


# =========================================================
# Build waveform sequence
# =========================================================

def build_sequence(icon):

    if len(icon) > 3:
        raise ValueError(
            "one icon can contain at most 3 effects"
        )

    seq = []

    for i, item in enumerate(icon):

        effect, gap_ms = item

        if not 1 <= effect <= 123:
            raise ValueError(
                "effect id must be 1..123"
            )

        seq.append(effect)

        # 如果后面还有 effect，
        # 并且 gap > 0，就加入 wait slot
        if (
            i < len(icon) - 1
            and gap_ms > 0
        ):
            seq.append(
                DRV2605.pause_ms(gap_ms)
            )

    # sequence end
    seq.append(0)

    if len(seq) > 8:
        raise ValueError(
            "DRV2605 waveform sequence exceeds 8 slots"
        )

    return seq


# =========================================================
# Haptic Controller
# =========================================================

class HapticController:

    def __init__(self):

        self.i2c = SoftI2C(
            sda=Pin(I2C_SDA),
            scl=Pin(I2C_SCL),
            freq=100000,
        )

        print(
            "I2C scan:",
            [hex(x) for x in self.i2c.scan()]
        )

        self.drv = DRV2605(
            self.i2c
        )

        self.drv.begin(
            motor="LRA"
        )

        self.lock = asyncio.Lock()

        # 当前是否处于 RTP realtime mode
        self.rtp_mode = False


    # =====================================================
    # Mode helpers
    # =====================================================

    def _set_internal_trigger(self):

        self.drv.set_mode(
            DRV2605.MODE_INTTRIG
        )

        self.rtp_mode = False


    def _set_realtime(self):

        if not self.rtp_mode:

            self.drv.set_mode(
                DRV2605.MODE_REALTIME
            )

            self.rtp_mode = True


    # =====================================================
    # Stop helpers
    # =====================================================

    def _stop_unlocked(self):

        # 如果当前在 RTP 模式，
        # 先把 RTP amplitude 写成 0
        try:

            if self.rtp_mode:

                self.drv.write_reg(
                    DRV2605.REG_RTPIN,
                    0
                )

        except Exception as e:

            print(
                "RTP stop failed:",
                e
            )


        # 停止 DRV2605
        try:

            self.drv.stop()

        except Exception as e:

            print(
                "DRV stop failed:",
                e
            )


        # 回到 Internal Trigger mode
        try:

            self._set_internal_trigger()

        except Exception as e:

            print(
                "set internal trigger failed:",
                e
            )


    async def stop(self):

        async with self.lock:

            print(
                "Stop haptic"
            )

            self._stop_unlocked()


    # =====================================================
    # Preset tactons
    # =====================================================

    async def play_icon(
        self,
        number
    ):

        if number not in HAPTIC_ICONS:

            raise ValueError(
                "unknown tacton id: {}".format(
                    number
                )
            )

        async with self.lock:

            icon = HAPTIC_ICONS[
                number
            ]

            seq = build_sequence(
                icon
            )

            print()
            print(
                "Play tacton:",
                number
            )

            print(
                "Definition:",
                icon
            )

            print(
                "DRV sequence:",
                seq
            )


            # 确保上一个 RTP / effect 已停止
            self._stop_unlocked()

            self._set_internal_trigger()


            # 让 DRV2605 自己播放整个 sequence
            self.drv.play_sequence(
                seq,
                wait=True
            )

            self.drv.stop()


    # =====================================================
    # Fixed Rough Slip
    #
    # 保留函数名 play_rough_slip，
    # 但内部现在完全不是随机的。
    #
    # Pattern:
    #
    # 55  -> 150 ms
    # 145 -> 150 ms
    # 55  -> 150 ms
    # 145 -> 150 ms
    # ...
    #
    # 总长度 = 2000 ms
    # =====================================================

    async def play_rough_slip(
        self,
        duration_ms=DEFAULT_SLIP_DURATION_MS
    ):

        # 为兼容原来的接口仍然保留参数，
        # 但 tacton 11 强制固定为 2 秒
        duration_ms = DEFAULT_SLIP_DURATION_MS

        async with self.lock:

            print()
            print(
                "Play tacton 11: Fixed Rough Slip"
            )

            print(
                "Pattern: Alternating Small-Large"
            )

            print(
                "Duration:",
                duration_ms,
                "ms"
            )


            # 停掉上一个 tacton
            self._stop_unlocked()

            # 切到 RTP realtime mode
            self._set_realtime()


            start = ticks_ms()

            step_index = 0


            while True:

                elapsed = ticks_diff(
                    ticks_ms(),
                    start
                )

                remaining = (
                    duration_ms
                    - elapsed
                )

                if remaining <= 0:
                    break


                # 在下面两个值之间循环：
                #
                # 55, 150ms
                # 145, 150ms
                value, step_duration = (
                    ROUGH_SLIP_MOTIF[
                        step_index
                        % len(ROUGH_SLIP_MOTIF)
                    ]
                )


                # 最后一步如果不足 150 ms，
                # 就自动截短，尽量让总时长接近 2 s
                if step_duration > remaining:

                    step_duration = (
                        remaining
                    )


                # 写入 RTP amplitude
                self.drv.write_reg(
                    DRV2605.REG_RTPIN,
                    value
                )


                # 保持这个 amplitude
                await asyncio.sleep_ms(
                    step_duration
                )


                step_index += 1


            # =================================================
            # Stop RTP
            # =================================================

            self.drv.write_reg(
                DRV2605.REG_RTPIN,
                0
            )

            self.drv.stop()

            self._set_internal_trigger()


            actual = ticks_diff(
                ticks_ms(),
                start
            )


            print(
                "Fixed Rough Slip finished"
            )

            print(
                "Actual duration:",
                actual,
                "ms"
            )


    # =====================================================
    # Generic tacton playback
    # =====================================================

    async def play_tacton(
        self,
        tacton_id,
        rough_duration_ms=DEFAULT_SLIP_DURATION_MS
    ):

        # tacton 11
        if (
            tacton_id
            == ROUGH_SLIP_TACTON_ID
        ):

            await self.play_rough_slip(
                rough_duration_ms
            )

            return


        # tacton 1 / 4 / 5 / 8 / 9 / 10
        await self.play_icon(
            tacton_id
        )


# =========================================================
# TCP command parser
# =========================================================

def parse_command(line):

    text = line.decode().strip()

    if not text:

        return None, None, None


    parts = text.split()

    command = parts[0].upper()


    # =====================================================
    # PING
    # STOP
    # =====================================================

    if command in HANDSHAKE_COMMANDS or command == "STOP":

        if len(parts) != 1:

            raise ValueError(
                "{} takes no arguments".format(
                    command
                )
            )

        return (
            command,
            None,
            None
        )


    # =====================================================
    # PLAY <tacton_id>
    #
    # 为兼容旧 PC 端：
    #
    # PLAY 11
    #
    # 或
    #
    # PLAY 11 2000
    #
    # 都可以。
    #
    # 但是 tacton 11 实际始终播放固定 2000 ms。
    # =====================================================

    if command == "PLAY":

        if len(parts) not in (
            2,
            3
        ):

            raise ValueError(
                "PLAY usage: PLAY <tacton_id> [rough_duration_ms]"
            )


        tacton_id = int(
            parts[1]
        )


        duration_ms = (
            DEFAULT_SLIP_DURATION_MS
        )


        # 保留旧协议兼容性
        if len(parts) == 3:

            duration_ms = int(
                parts[2]
            )


        return (
            command,
            tacton_id,
            duration_ms
        )


    # =====================================================
    # Backward-compatible shorthand
    #
    # 直接发送：
    #
    # "1\n"
    # "4\n"
    # "11\n"
    #
    # =====================================================

    if len(parts) == 1:

        tacton_id = int(
            parts[0]
        )

        return (
            "PLAY",
            tacton_id,
            DEFAULT_SLIP_DURATION_MS
        )


    raise ValueError(
        "unknown command: {}".format(
            text
        )
    )


# =========================================================
# TCP Server
# =========================================================

class HapticTCPServer:

    def __init__(
        self,
        controller
    ):

        self.controller = (
            controller
        )

        self.sock = None


    async def start(
        self,
        port=TCP_PORT
    ):

        addr = socket.getaddrinfo(
            "0.0.0.0",
            port
        )[0][-1]


        self.sock = (
            socket.socket()
        )


        self.sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )


        self.sock.bind(
            addr
        )


        self.sock.listen(
            1
        )


        self.sock.setblocking(
            False
        )


        print()
        print(
            "DRV2605 tacton TCP server started on port:",
            port
        )

        print(
            "Commands:"
        )

        print(
            "  PLAY <id> [rough_ms]"
        )

        print(
            "  STOP"
        )

        print(
            "  PING"
        )
        print(
            "  HELLO"
        )

        print(
            "Valid tacton ids:",
            VALID_TACTON_IDS
        )

        print(
            "Tacton 11 = fixed alternating slip, 2000 ms"
        )


        while True:

            try:

                client, addr = (
                    self.sock.accept()
                )

                print(
                    "Client connected:",
                    addr
                )


                client.setblocking(
                    False
                )


                asyncio.create_task(
                    self.handle_client(
                        client
                    )
                )


            except OSError:

                await asyncio.sleep_ms(
                    10
                )


            await asyncio.sleep_ms(
                0
            )


    # =====================================================
    # Send response
    # =====================================================

    def _send_response(
        self,
        client,
        text
    ):

        try:

            client.send(
                (
                    text
                    + "\n"
                ).encode()
            )

        except Exception as e:

            print(
                "send response failed:",
                e
            )


    # =====================================================
    # Client handler
    # =====================================================

    async def handle_client(
        self,
        client
    ):

        buf = b""


        try:

            while True:

                try:

                    data = client.recv(
                        64
                    )


                    if data:

                        buf += data


                        # 命令使用换行分隔
                        while b"\n" in buf:

                            line, buf = (
                                buf.split(
                                    b"\n",
                                    1
                                )
                            )

                            line = (
                                line.strip()
                            )


                            if not line:

                                continue


                            try:

                                (
                                    command,
                                    tacton_id,
                                    duration_ms
                                ) = parse_command(
                                    line
                                )


                                if command is None:

                                    continue


                                # =================================
                                # PING
                                # =================================

                                if command in HANDSHAKE_COMMANDS:

                                    self._send_response(
                                        client,
                                        HANDSHAKE_RESPONSE
                                    )

                                    continue


                                # =================================
                                # STOP
                                # =================================

                                if command == "STOP":

                                    await (
                                        self.controller.stop()
                                    )

                                    self._send_response(
                                        client,
                                        "OK STOP"
                                    )

                                    continue


                                # =================================
                                # Validate tacton ID
                                # =================================

                                if (
                                    tacton_id
                                    not in VALID_TACTON_IDS
                                ):

                                    raise ValueError(
                                        "unknown tacton id: {}".format(
                                            tacton_id
                                        )
                                    )


                                # =================================
                                # Tell PC that command was accepted
                                # =================================

                                self._send_response(
                                    client,
                                    "OK PLAY {}".format(
                                        tacton_id
                                    )
                                )


                                # =================================
                                # Play tacton
                                # =================================

                                await (
                                    self.controller.play_tacton(
                                        tacton_id,
                                        duration_ms
                                    )
                                )


                            except Exception as e:

                                print(
                                    "Bad command:",
                                    line,
                                    e
                                )

                                self._send_response(
                                    client,
                                    "ERR {}".format(
                                        e
                                    )
                                )


                    elif data == b"":

                        print(
                            "Client disconnected"
                        )

                        break


                except OSError:

                    # non-blocking socket:
                    # 没有数据时会走这里
                    await asyncio.sleep_ms(
                        1
                    )


                await asyncio.sleep_ms(
                    0
                )


        finally:

            # 客户端断开时确保振动停止
            try:

                await (
                    self.controller.stop()
                )

            except Exception as e:

                print(
                    "stop on disconnect error:",
                    e
                )


            try:

                client.close()

            except Exception:

                pass


            print(
                "Client closed"
            )


# =========================================================
# Main
# =========================================================

async def main():

    controller = (
        HapticController()
    )

    server = (
        HapticTCPServer(
            controller
        )
    )

    await server.start(
        TCP_PORT
    )


# =========================================================
# Run
# =========================================================

try:

    asyncio.run(
        main()
    )


except KeyboardInterrupt:

    print(
        "KeyboardInterrupt"
    )


finally:

    try:

        asyncio.new_event_loop()

    except Exception:

        pass


    print(
        "Program stopped"
    )
