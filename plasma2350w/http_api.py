# http_api.py — Local REST API for Lightbar
# Version: 2.0.0
#
# For curl, scripts and debugging. Home Assistant uses MQTT, not this.
#
# Security:
#   • If API_TOKEN is set in secrets.py, every request needs
#     "Authorization: Bearer <token>" (401 otherwise).
#   • State only changes on POST, so a web page can't flip the light with
#     an <img src=…> (GET is read-only). No CORS headers are sent.
#   • Requests are size- and time-limited; bad input gives 400, not a crash.
#
#   GET  /status                                    → full state
#   GET  /info                                      → device info
#   POST /on | /off | /toggle            [?light=N] → all lights, or light N
#   POST /brightness?value=0-100         [&light=N] → without light: scales all
#   POST /color?light=N&h=0-360&s=0-100             → hue / saturation
#   POST /color?light=N&r=0-255&g=0-255&b=0-255     → RGB
#   POST /randomize
#
# Parameters may also be sent as a JSON object body with the same names.

import asyncio
import json

_MAX_HEADER_LINES = 32
_MAX_LINE = 512
_MAX_BODY = 1024
_TIMEOUT_S = 5

_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
            404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large",
            500: "Internal Server Error"}


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class RestApi:
    def __init__(self, bar, token=None, info=None):
        self.bar = bar
        self.token = token
        self.info = info or {}

    async def start(self, port):
        # Keep a reference: the server stops if it is garbage collected.
        self._server = await asyncio.start_server(self._handle, "0.0.0.0", port)

    # ── Connection handling ───────────────────────────────────────

    async def _handle(self, reader, writer):
        try:
            try:
                method, path, query, headers, body = await asyncio.wait_for(
                    _read_request(reader), _TIMEOUT_S)
                self._authorize(headers)
                status, payload = 200, self._route(method, path, _params(query, body))
            except HTTPError as e:
                status, payload = e.status, {"error": e.message}
            except asyncio.TimeoutError:
                status, payload = 400, {"error": "request timeout"}
            except Exception as e:  # noqa: BLE001 — report, never crash the server
                print("[HTTP] Error: {!r}".format(e))
                status, payload = 500, {"error": "internal error"}
            await _respond(writer, status, payload)
        except Exception:  # noqa: BLE001 — client went away
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    def _authorize(self, headers):
        if not self.token:
            return
        supplied = headers.get("authorization", "")
        if not _consteq(supplied, "Bearer " + self.token):
            raise HTTPError(401, "missing or invalid bearer token")

    # ── Routing ───────────────────────────────────────────────────

    def _route(self, method, path, p):
        bar = self.bar
        if path in ("/status", "/info"):
            if method != "GET":
                raise HTTPError(405, "use GET")
            return bar.state() if path == "/status" else self.info

        actions = ("/on", "/off", "/toggle", "/brightness", "/color", "/randomize")
        if path not in actions:
            raise HTTPError(404, "not found")
        if method != "POST":
            raise HTTPError(405, "use POST")

        index = _light_index(p, len(bar.lights))

        if path == "/on" or path == "/off":
            on = path == "/on"
            if index is None:
                bar.set_all(on=on)
            else:
                bar.set_light(index, on=on)
        elif path == "/toggle":
            if index is None:
                bar.toggle_all()
            else:
                bar.set_light(index, on=not bar.lights[index].on)
        elif path == "/brightness":
            value = _number(p, "value", 0, 100) / 100
            if index is None:
                bar.set_all(brightness=value)
            else:
                bar.set_light(index, brightness=value)
        elif path == "/color":
            if index is None:
                raise HTTPError(400, "'light' is required")
            if "r" in p or "g" in p or "b" in p:
                h, s = _rgb_to_hs(_number(p, "r", 0, 255), _number(p, "g", 0, 255),
                                  _number(p, "b", 0, 255))
            else:
                h = _number(p, "h", 0, 360) / 360
                s = _number(p, "s", 0, 100) / 100
            bar.set_light(index, hue=h, sat=s)
        else:
            bar.randomize()
        return bar.state()


# ── Request / response helpers ────────────────────────────────────

async def _read_request(reader):
    line = await reader.readline()
    if len(line) > _MAX_LINE:
        raise HTTPError(400, "request line too long")
    parts = line.decode().split()
    if len(parts) != 3:
        raise HTTPError(400, "malformed request line")
    method, target = parts[0], parts[1]
    path, query = _split(target, "?")

    headers = {}
    for _ in range(_MAX_HEADER_LINES):
        line = await reader.readline()
        if len(line) > _MAX_LINE:
            raise HTTPError(400, "header too long")
        line = line.decode().strip()
        if not line:
            break
        key, value = _split(line, ":")
        headers[key.strip().lower()] = value.strip()
    else:
        raise HTTPError(400, "too many headers")

    body = b""
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        raise HTTPError(400, "bad Content-Length")
    if length > _MAX_BODY or length < 0:
        raise HTTPError(413, "body too large")
    if length:
        body = await reader.readexactly(length)
    return method, path, query, headers, body


async def _respond(writer, status, payload):
    body = json.dumps(payload)
    head = ("HTTP/1.1 {} {}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n\r\n").format(status, _REASONS.get(status, ""), len(body))
    writer.write((head + body).encode())
    await writer.drain()


def _params(query, body):
    params = {}
    if body:
        try:
            data = json.loads(body)
        except ValueError:
            raise HTTPError(400, "body is not valid JSON")
        if not isinstance(data, dict):
            raise HTTPError(400, "body must be a JSON object")
        params.update(data)
    for pair in query.split("&"):
        if pair:
            key, value = _split(pair, "=")
            params[key] = value
    return params


def _split(text, sep):
    """"a<sep>b" → ("a", "b"); no separator → (text, "")."""
    parts = text.split(sep, 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _number(p, key, lo, hi):
    if key not in p:
        raise HTTPError(400, "'{}' is required".format(key))
    try:
        v = float(p[key])
    except (TypeError, ValueError):
        raise HTTPError(400, "'{}' must be a number".format(key))
    if not lo <= v <= hi:
        raise HTTPError(400, "'{}' must be {}-{}".format(key, lo, hi))
    return v


def _light_index(p, count):
    raw = p.get("light", p.get("idx"))         # "idx" kept for old scripts
    if raw is None:
        return None
    try:
        index = int(raw)
    except (TypeError, ValueError):
        raise HTTPError(400, "'light' must be an integer")
    if not 0 <= index < count:
        raise HTTPError(400, "'light' must be 0-{}".format(count - 1))
    return index


def _rgb_to_hs(r, g, b):
    r, g, b = r / 255, g / 255, b / 255
    cmax, cmin = max(r, g, b), min(r, g, b)
    delta = cmax - cmin
    s = 0.0 if cmax == 0 else delta / cmax
    if delta == 0:
        h = 0.0
    elif cmax == r:
        h = ((g - b) / delta) % 6
    elif cmax == g:
        h = (b - r) / delta + 2
    else:
        h = (r - g) / delta + 4
    return (h / 6) % 1.0, s


def _consteq(a, b):
    """Compare without leaking how many leading characters matched."""
    a, b = a.encode(), b.encode()
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0
