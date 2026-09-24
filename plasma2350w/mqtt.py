# mqtt.py — Minimal asyncio MQTT 3.1.1 client for Lightbar
# Version: 1.0.0
#
# Just what Lightbar needs, and nothing that blocks the event loop:
#   • CONNECT with username/password and a retained Last Will
#   • PUBLISH / SUBSCRIBE at QoS 0
#   • Keep-alive pings, and automatic reconnect with back-off
#
# Works on MicroPython (asyncio) and CPython (used by the host tests).
#
#   client = MQTTClient("lightbar_abc123", "192.168.1.10", user=..., password=...,
#                       will=("lightbar/abc123/availability", b"offline"))
#   client.on_connect = async_fn()           # (re)subscribe + publish here
#   client.on_message = fn(topic: str, payload: bytes)
#   asyncio.create_task(client.run())

import asyncio
import struct

try:
    from time import ticks_ms, ticks_diff
except ImportError:  # CPython
    from time import monotonic as _mono

    def ticks_ms():
        return int(_mono() * 1000)

    def ticks_diff(a, b):
        return a - b


_CONNECT = 0x10
_CONNACK = 0x20
_PUBLISH = 0x30
_SUBSCRIBE = 0x82
_PINGREQ = 0xC0

_MAX_PACKET = 4096          # Ignore (and skip) anything bigger than this
_RECONNECT_MIN_S = 2
_RECONNECT_MAX_S = 60


class MQTTError(Exception):
    pass


def _str(s):
    b = s.encode() if isinstance(s, str) else s
    return struct.pack("!H", len(b)) + b


def _packet(header, body):
    """Fixed header + remaining-length varint + body."""
    n = len(body)
    out = bytearray([header])
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | 0x80 if n else byte)
        if not n:
            break
    return bytes(out) + body


class MQTTClient:
    def __init__(self, client_id, host, port=1883, user=None, password=None,
                 keepalive=30, will=None):
        self.client_id = client_id
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.keepalive = keepalive
        self.will = will                # (topic, payload) — sent retained
        self.on_connect = None          # async callable()
        self.on_message = None          # callable(topic, payload)
        self.connected = False
        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock()
        self._pid = 0
        self._last_rx = 0

    # ── Public API ────────────────────────────────────────────────

    async def run(self, can_connect=None):
        """Connect, dispatch messages and reconnect forever.

        `can_connect` is an optional callable; while it returns False
        (e.g. WiFi is down) no connection attempt is made.
        """
        delay = _RECONNECT_MIN_S
        while True:
            if can_connect is not None and not can_connect():
                await asyncio.sleep(1)
                continue
            try:
                await self._connect()
                delay = _RECONNECT_MIN_S
                print("[MQTT] Connected to {}:{}".format(self.host, self.port))
                if self.on_connect:
                    await self.on_connect()
                await self._serve()
            except Exception as e:  # noqa: BLE001 — any failure means reconnect
                print("[MQTT] Disconnected: {!r}".format(e))
            await self._close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_S)

    async def publish(self, topic, payload, retain=False):
        """Publish at QoS 0. Returns False (instead of raising) when offline."""
        if not self.connected:
            return False
        if isinstance(payload, str):
            payload = payload.encode()
        pkt = _packet(_PUBLISH | (1 if retain else 0), _str(topic) + payload)
        try:
            await self._send(pkt)
            return True
        except Exception as e:  # noqa: BLE001
            print("[MQTT] Publish failed: {!r}".format(e))
            await self._close()
            return False

    async def subscribe(self, topic):
        self._pid = self._pid % 0xFFFF + 1
        body = struct.pack("!H", self._pid) + _str(topic) + b"\x00"
        await self._send(_packet(_SUBSCRIBE, body))

    # ── Internals ─────────────────────────────────────────────────

    async def _send(self, pkt):
        async with self._lock:
            self._writer.write(pkt)
            await self._writer.drain()

    async def _connect(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), 10)

        flags = 0x02                                    # clean session
        payload = _str(self.client_id)
        if self.will:
            flags |= 0x04 | 0x20                        # will flag + will retain
            payload += _str(self.will[0]) + _str(self.will[1])
        if self.user:
            flags |= 0x80
            payload += _str(self.user)
            if self.password:
                flags |= 0x40
                payload += _str(self.password)
        var = _str("MQTT") + bytes([4, flags]) + struct.pack("!H", self.keepalive)
        self._writer.write(_packet(_CONNECT, var + payload))
        await self._writer.drain()

        header, body = await asyncio.wait_for(self._read_packet(), 10)
        if header != _CONNACK or len(body) != 2:
            raise MQTTError("unexpected reply to CONNECT")
        if body[1] != 0:
            reasons = {4: "bad username or password", 5: "not authorised"}
            raise MQTTError("CONNECT refused: " + reasons.get(body[1], str(body[1])))
        self.connected = True
        self._last_rx = ticks_ms()

    async def _read_packet(self):
        header = (await self._reader.readexactly(1))[0]
        length, shift = 0, 0
        while True:
            byte = (await self._reader.readexactly(1))[0]
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
            if shift > 21:
                raise MQTTError("malformed remaining length")
        if length > _MAX_PACKET:
            # Drain in chunks so the stream stays in sync, then drop it.
            while length:
                chunk = min(length, 512)
                await self._reader.readexactly(chunk)
                length -= chunk
            return header, None
        body = await self._reader.readexactly(length) if length else b""
        self._last_rx = ticks_ms()
        return header, body

    async def _serve(self):
        pinger = asyncio.create_task(self._ping_loop())
        try:
            while True:
                header, body = await self._read_packet()
                if body is None:
                    continue
                if header & 0xF0 == _PUBLISH:
                    self._dispatch(header, body)
                # SUBACK / PINGRESP need no action: any packet refreshes _last_rx.
        finally:
            pinger.cancel()

    def _dispatch(self, header, body):
        tlen = struct.unpack("!H", body[:2])[0]
        topic = bytes(body[2:2 + tlen]).decode()
        pos = 2 + tlen
        if header & 0x06:                               # QoS > 0: skip packet id
            pos += 2
        if self.on_message:
            try:
                self.on_message(topic, bytes(body[pos:]))
            except Exception as e:  # noqa: BLE001 — never let a handler kill the link
                print("[MQTT] Handler error on {}: {!r}".format(topic, e))

    async def _ping_loop(self):
        interval = max(self.keepalive // 2, 1)
        while True:
            await asyncio.sleep(interval)
            if ticks_diff(ticks_ms(), self._last_rx) > self.keepalive * 1500:
                # No traffic (not even PINGRESP) for 1.5× keep-alive: link is dead.
                await self._close()
                return
            await self._send(_packet(_PINGREQ, b""))

    async def _close(self):
        # No DISCONNECT packet on purpose: we only ever close because the link
        # failed, and an abrupt close makes the broker publish our Last Will
        # ("offline"), which is exactly what Home Assistant should see.
        self.connected = False
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
