"""Mock logiciel de l'ESP32-CAM (profil `sim`, remplace `cam-01`).

Imite le comportement HTTP du firmware d'exemple « CameraWebServer » :
  - serveur principal : GET /capture (JPEG), GET /status (JSON), GET /control?var=..&val=..
  - serveur de flux (port principal + 1) : GET /stream (MJPEG, multipart/x-mixed-replace)
Les images sont générées (dégradé, carré mobile, heure UTC, numéro d'image) : on voit
à l'oeil si l'enregistreur perd, duplique ou réordonne des images.

Pannes injectables pendant les tests (réservé au mock, absent du vrai firmware) :
  GET /__fault?mode=none|drop|stall|down
    drop  : coupe les flux en cours (le WiFi saute), les nouvelles connexions repassent
    stall : les flux restent ouverts mais n'envoient plus rien (caméra figée)
    down  : toutes les requêtes reçoivent 503 (caméra injoignable)

Ports : le vrai firmware écoute sur 80 et 81 ; ici 8080 et 8081 par défaut (pas de root).
L'enregistreur lit son URL dans sa configuration, jamais en dur.

Usage : python3 esp32cam_mock.py [--port 8080] [--fps 10] [--size 320x240] [--max-stream-clients 1]
Dépendance : Pillow.
"""
import argparse
import io
import json
import select
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw

BOUNDARY = "123456789000000000000987654321"  # identique au firmware d'exemple


class State:
    def __init__(self, args):
        self.cam_id = args.cam_id
        self.fps = args.fps
        self.w, self.h = (int(x) for x in args.size.split("x"))
        self.max_clients = args.max_stream_clients
        self.start = time.time()
        self.mode = "none"
        self.generation = 0  # incrémenté par `drop` : les flux de l'ancienne génération s'arrêtent
        self.clients = 0
        self.lock = threading.Lock()
        self.controls = {"framesize": 5, "quality": 12}

    def frame(self, n):
        """JPEG de l'image numéro n (déterministe pour un n donné, hors heure)."""
        img = Image.new("RGB", (self.w, self.h))
        d = ImageDraw.Draw(img)
        for y in range(0, self.h, 4):
            c = int(40 + 100 * y / self.h)
            d.rectangle([0, y, self.w, y + 4], fill=(c, c, 90))
        x = (n * 5) % max(1, self.w - 30)
        d.rectangle([x, self.h // 2 - 15, x + 30, self.h // 2 + 15], fill=(240, 200, 40))
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        d.text((6, 6), f"{self.cam_id}  {now}Z  #{n}", fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return buf.getvalue()


def make_handler(state, is_stream_server):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body, extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/__fault" and not is_stream_server:
                mode = q.get("mode", ["none"])[0]
                if mode not in ("none", "drop", "stall", "down"):
                    return self._send(400, "text/plain", b"mode inconnu")
                if mode == "drop":
                    state.generation += 1
                    mode = "none"  # drop est ponctuel : le prochain flux repart normalement
                state.mode = mode
                return self._send(200, "text/plain", b"ok")
            if url.path == "/__state" and not is_stream_server:
                body = json.dumps({"mode": state.mode, "clients": state.clients}).encode()
                return self._send(200, "application/json", body)
            if state.mode == "down":
                return self._send(503, "text/plain", b"camera down")
            if is_stream_server and url.path == "/stream":
                return self._stream()
            if not is_stream_server:
                if url.path == "/capture":
                    n = int((time.time() - state.start) * state.fps)
                    ts = f"{time.time():.6f}"
                    return self._send(200, "image/jpeg", state.frame(n), [
                        ("Content-Disposition", "inline; filename=capture.jpg"),
                        ("X-Timestamp", ts)])
                if url.path == "/status":
                    body = json.dumps(dict(state.controls, cam_id=state.cam_id)).encode()
                    return self._send(200, "application/json", body)
                if url.path == "/control":
                    var, val = q.get("var", [None])[0], q.get("val", [None])[0]
                    if var in state.controls and val is not None and val.lstrip("-").isdigit():
                        state.controls[var] = int(val)
                        return self._send(200, "text/plain", b"")
                    return self._send(404, "text/plain", b"unknown control")
            return self._send(404, "text/plain", b"not found")

        def _peer_closed(self):
            """Vrai si le client a fermé la connexion (utile quand on n'écrit plus, ex. stall)."""
            r, _, _ = select.select([self.connection], [], [], 0)
            if not r:
                return False
            try:
                return self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        def _stream(self):
            with state.lock:
                if state.clients >= state.max_clients:
                    return self._send(503, "text/plain", b"too many stream clients")
                state.clients += 1
            gen = state.generation
            try:
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace;boundary={BOUNDARY}")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                n = int((time.time() - state.start) * state.fps)
                period = 1.0 / state.fps
                nxt = time.time()
                while state.generation == gen and state.mode != "down":
                    if self._peer_closed():
                        break
                    if state.mode == "stall":
                        time.sleep(0.1)
                        continue
                    jpg = state.frame(n)
                    ts = time.time()
                    head = (f"\r\n--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                            f"Content-Length: {len(jpg)}\r\n"
                            f"X-Timestamp: {int(ts)}.{int((ts % 1) * 1e6):06d}\r\n\r\n")
                    self.wfile.write(head.encode() + jpg)
                    self.wfile.flush()
                    n += 1
                    nxt += period
                    time.sleep(max(0.0, nxt - time.time()))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                self.close_connection = True
                with state.lock:
                    state.clients -= 1

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080, help="serveur principal ; le flux est sur port+1")
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--size", default="320x240")
    p.add_argument("--cam-id", default="cam-01")
    p.add_argument("--max-stream-clients", type=int, default=1,
                   help="prudent : l'ESP32 supporte mal plusieurs flux ; à confirmer sur la carte")
    args = p.parse_args()
    state = State(args)
    main_srv = ThreadingHTTPServer((args.host, args.port), make_handler(state, False))
    stream_srv = ThreadingHTTPServer((args.host, args.port + 1), make_handler(state, True))
    for srv in (main_srv, stream_srv):
        srv.daemon_threads = True
    threading.Thread(target=stream_srv.serve_forever, daemon=True).start()
    print(f"mock {args.cam_id}: http://{args.host}:{args.port}/capture  "
          f"http://{args.host}:{args.port + 1}/stream  ({args.size} @ {args.fps} fps)", flush=True)
    try:
        main_srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
