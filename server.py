import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "3000"))
WIDTH = 1920
HEIGHT = 1080
COOLDOWN_MS = 60_000
CHANGE_LIMIT = 5_000
if getattr(sys, "frozen", False):
    PUBLIC_DIR = Path(sys._MEIPASS) / "public"
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MinPaint"
else:
    PUBLIC_DIR = Path(__file__).parent / "public"
    DATA_DIR = Path(__file__).parent / "data"
STATE_FILE = DATA_DIR / "board.json"
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
STATE_LOCK = threading.RLock()

pixels = {}
changes = []
sequence = 0
cooldowns = {}


def load_state():
    global pixels, changes, sequence, cooldowns
    try:
        with STATE_FILE.open(encoding="utf-8") as state_file:
            state = json.load(state_file)
    except FileNotFoundError:
        return

    if not isinstance(state, dict):
        raise ValueError("Invalid board state")

    pixels = {
        index: color
        for index, color in (state.get("pixels") or {}).items()
        if str(index).isdecimal()
        and int(index) < WIDTH * HEIGHT
        and isinstance(color, str)
        and COLOR_PATTERN.fullmatch(color)
    }
    stored_sequence = state.get("sequence", 0)
    sequence = stored_sequence if type(stored_sequence) is int and stored_sequence >= 0 else 0
    cooldowns = {
        visitor: timestamp
        for visitor, timestamp in (state.get("cooldowns") or {}).items()
        if isinstance(timestamp, (int, float)) and timestamp > 0
    }
    stored_changes = state.get("changes") or []
    changes = [
        change
        for change in stored_changes
        if isinstance(change, dict)
        and type(change.get("seq")) is int
        and type(change.get("index")) is int
        and 0 <= change["index"] < WIDTH * HEIGHT
        and isinstance(change.get("color"), str)
        and COLOR_PATTERN.fullmatch(change["color"])
    ][-CHANGE_LIMIT:]


def persist_state():
    temporary_file = None
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATE_FILE.with_suffix(".tmp").open("w", encoding="utf-8") as output:
            json.dump(
                {
                    "pixels": pixels,
                    "sequence": sequence,
                    "cooldowns": cooldowns,
                    "changes": changes,
                },
                output,
                separators=(",", ":"),
            )
            output.flush()
            os.fsync(output.fileno())
        temporary_file = STATE_FILE.with_suffix(".tmp")
        os.replace(temporary_file, STATE_FILE)
    except OSError:
        if temporary_file and temporary_file.exists():
            temporary_file.unlink()
        raise


class MinPaintHandler(BaseHTTPRequestHandler):
    server_version = "MinPaint/1.0"

    def send_json(self, status, value):
        contents = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if hasattr(self, "new_cookie"):
            self.send_header("Set-Cookie", self.new_cookie)
        self.send_header("Content-Length", str(len(contents)))
        self.end_headers()
        self.wfile.write(contents)

    def get_visitor(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        visitor = cookie.get("pixel-visitor")
        if visitor and re.fullmatch(r"[a-f0-9]{32}", visitor.value):
            return visitor.value

        visitor_id = secrets.token_hex(16)
        self.new_cookie = (
            f"pixel-visitor={visitor_id}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
        )
        return visitor_id

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/board":
            with STATE_LOCK:
                visitor = self.get_visitor()
                board = {
                    "width": WIDTH,
                    "height": HEIGHT,
                    "pixels": pixels.copy(),
                    "sequence": sequence,
                    "nextPaintAt": cooldowns.get(visitor, 0),
                }
            self.send_json(HTTPStatus.OK, board)
            return

        if parsed.path == "/api/changes":
            query = parse_qs(parsed.query)
            try:
                after = int(query.get("after", [""])[0])
            except ValueError:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid change cursor"})
                return
            with STATE_LOCK:
                if after < 0 or after > sequence:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid change cursor"})
                elif changes and after < changes[0]["seq"] - 1:
                    self.send_json(HTTPStatus.OK, {"reset": True, "sequence": sequence})
                else:
                    self.send_json(
                        HTTPStatus.OK,
                        {
                            "reset": False,
                            "sequence": sequence,
                            "changes": [change for change in changes if change["seq"] > after],
                        },
                    )
            return

        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if parsed.path not in files:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        filename, content_type = files[parsed.path]
        try:
            contents = (PUBLIC_DIR / filename).read_bytes()
        except OSError:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not load the website"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(contents)))
        self.end_headers()
        self.wfile.write(contents)

    def do_POST(self):
        global sequence
        if urlsplit(self.path).path != "/api/paint":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1024:
                raise ValueError("Request body is too large or empty")
            paint = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.close_connection = True
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body must be valid JSON"})
            return

        x = paint.get("x") if isinstance(paint, dict) else None
        y = paint.get("y") if isinstance(paint, dict) else None
        color = paint.get("color") if isinstance(paint, dict) else None
        if (
            type(x) is not int
            or type(y) is not int
            or not 0 <= x < WIDTH
            or not 0 <= y < HEIGHT
            or not isinstance(color, str)
            or not COLOR_PATTERN.fullmatch(color)
        ):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Choose a valid pixel and color"})
            return

        with STATE_LOCK:
            visitor = self.get_visitor()
            now = int(time.time() * 1000)
            next_paint_at = cooldowns.get(visitor, 0)
            if now < next_paint_at:
                self.send_json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {"error": "Your next pixel is not ready yet", "nextPaintAt": next_paint_at},
                )
                return

            index = y * WIDTH + x
            normalized_color = color.lower()
            previous_color = pixels.get(str(index))
            previous_cooldown = cooldowns.get(visitor)
            sequence += 1
            pixels[str(index)] = normalized_color
            cooldowns[visitor] = now + COOLDOWN_MS
            changes.append({"seq": sequence, "index": index, "color": normalized_color})
            if len(changes) > CHANGE_LIMIT:
                del changes[:-CHANGE_LIMIT]

            try:
                persist_state()
            except OSError as error:
                sequence -= 1
                if previous_color is None:
                    pixels.pop(str(index), None)
                else:
                    pixels[str(index)] = previous_color
                if previous_cooldown is None:
                    cooldowns.pop(visitor, None)
                else:
                    cooldowns[visitor] = previous_cooldown
                changes.pop()
                print(f"Could not save pixel: {error}", flush=True)
                self.send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "Could not save your pixel. Please try again."},
                )
                return

            self.send_json(
                HTTPStatus.OK,
                {
                    "sequence": sequence,
                    "index": index,
                    "color": normalized_color,
                    "nextPaintAt": cooldowns[visitor],
                },
            )

    def log_message(self, format_string, *args):
        print(f"{self.address_string()} - {format_string % args}", flush=True)


if __name__ == "__main__":
    load_state()
    server = ThreadingHTTPServer((HOST, PORT), MinPaintHandler)
    server.daemon_threads = True
    port = server.server_port
    local_url = f"http://localhost:{port}"
    print(f"\nMinPaint is running at {local_url}", flush=True)
    print("Keep this window open while people are using the canvas.", flush=True)

    try:
        lan_addresses = sorted(
            {
                result[4][0]
                for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                if not result[4][0].startswith("127.")
            }
        )
    except socket.gaierror:
        lan_addresses = []
    for address in lan_addresses:
        print(f"On your Wi-Fi: http://{address}:{port}", flush=True)
    print(
        f"To make it public, allow TCP port {port} through Windows Firewall and "
        f"forward that port on your router to this PC.",
        flush=True,
    )
    print(
        f"Then share http://YOUR-PUBLIC-IP:{port} (find your public IP using a search engine). "
        "This address uses HTTP, not HTTPS.",
        flush=True,
    )
    threading.Timer(1, webbrowser.open, args=(local_url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMinPaint stopped.", flush=True)
        server.server_close()
