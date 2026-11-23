#!/usr/bin/env python3
"""Faux nœuds Modbus RTU (Arduino) : sert la table du contrat (CONTRAT.md §1).

Plusieurs esclaves sur un même port série, des mesures qui évoluent, et des pannes que l'on
déclenche à chaud par une petite interface HTTP locale. Écrit sans pymodbus : le protocole est
court, et on garde la main sur les cas tordus (silence, CRC faux, retard).

    python3 sim_modbus.py --port /tmp/pharma-ttyA --time-scale 20 -v

Registres (adresses à partir de 0) :
  entrée FC04 : 0 température (int16, °C x100)  1 humidité (u16, % x100)  2 pression (u16, hPa x10)
                3 statut (bit0 sensor_ok, bit1 temp_alarm)  4-5 uptime (u32, mot fort en 4)
                6 séquence  7-8 numéro de série (u32, mot fort en 7)
  discrète FC02 : 0 détecteur de mouvement
  maintien FC03/06/16 : 0 période (s, 1 à 3600)  1 seuil bas (°C x100)  2 seuil haut (°C x100)

Pannes (GET /__fault?slave=2&mode=...) : none, silent, invalid, frozen, badserial, zeroserial,
badcrc, slow (avec &delay_ms=200). Autres : /__temp?slave=1&value=9.3 (value=none pour annuler),
/__pir?slave=2&value=1, /__reset_config?slave=1 (simule un redémarrage de l'Arduino), /__state.
"""
import argparse
import json
import math
import os
import random
import select
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import serial

INVALID_TEMP = 0x8000
INVALID_U16 = 0xFFFF
HR_DEFAULT = (10, 200, 800)
IR_SIZE, HR_SIZE, DI_SIZE = 9, 3, 1
FAULTS = ("none", "silent", "invalid", "frozen", "badserial", "zeroserial", "badcrc", "slow")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    c = crc16(frame)
    return frame + bytes([c & 0xFF, c >> 8])  # octet faible d'abord


def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


class Node:
    def __init__(self, addr: int, serial_no: int, has_pressure: bool, time_scale: float, seed: int):
        self.addr, self.serial_no, self.has_pressure = addr, serial_no, has_pressure
        self.time_scale = time_scale
        self.lock = threading.Lock()
        self.rng = random.Random(seed)
        self.hr = list(HR_DEFAULT)
        self.pir = False
        self.fault, self.delay_ms = "none", 0
        self.temp_override = None
        self.seq = 0
        self.t0 = time.monotonic()
        self.temp = self.hum = self.press = 0
        self.sensor_ok = True
        self.next_update = 0.0
        self.measure()

    def measure(self) -> None:
        """Une mesure, comme le ferait l'Arduino à chaque période."""
        with self.lock:
            t = time.monotonic() - self.t0
            if self.fault != "frozen":
                self.seq = (self.seq + 1) & 0xFFFF
            if self.fault == "invalid":
                self.sensor_ok = False
                self.temp, self.hum, self.press = INVALID_TEMP, INVALID_U16, INVALID_U16
            else:
                self.sensor_ok = True
                c = self.temp_override if self.temp_override is not None else (
                    4.5 + 0.8 * math.sin(2 * math.pi * t / 600) + self.rng.gauss(0, 0.05))
                self.temp = round(c * 100) & 0xFFFF
                self.hum = round((45.0 + self.rng.gauss(0, 0.3)) * 100)
                self.press = round((1013.2 + self.rng.gauss(0, 0.2)) * 10) if self.has_pressure else INVALID_U16
            self.next_update = time.monotonic() + self.hr[0] / self.time_scale

    def input_regs(self) -> list[int]:
        with self.lock:
            alarm = self.sensor_ok and (s16(self.temp) < s16(self.hr[1]) or s16(self.temp) > s16(self.hr[2]))
            status = (1 if self.sensor_ok else 0) | (2 if alarm else 0)
            uptime = int((time.monotonic() - self.t0) * self.time_scale)
            serial_no = {"badserial": self.serial_no + 1000, "zeroserial": 0}.get(self.fault, self.serial_no)
            return [self.temp, self.hum, self.press, status, (uptime >> 16) & 0xFFFF, uptime & 0xFFFF,
                    self.seq, (serial_no >> 16) & 0xFFFF, serial_no & 0xFFFF]

    @staticmethod
    def hr_value_ok(index: int, value: int) -> bool:
        if index == 0:
            return 1 <= value <= 3600
        return -5000 <= s16(value) <= 10000  # -50 à +100 °C


def exception(addr: int, fc: int, code: int) -> bytes:
    return with_crc(bytes([addr, fc | 0x80, code]))


class Bus:
    def __init__(self, nodes: dict[int, Node]):
        self.nodes = nodes

    def respond(self, frame: bytes):
        """Retourne (réponse ou None, nœud concerné)."""
        if len(frame) < 4 or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            return None, None  # trame corrompue : on se tait, comme un vrai esclave
        addr, fc, body = frame[0], frame[1], frame[2:-2]
        if addr == 0:  # diffusion : écritures seulement, jamais de réponse
            if fc in (6, 16):
                for node in self.nodes.values():
                    if node.fault != "silent":
                        self._execute(node, 0, fc, body)
            return None, None
        node = self.nodes.get(addr)
        if node is None or node.fault == "silent":
            return None, node
        return self._execute(node, addr, fc, body), node

    def _execute(self, node: Node, addr: int, fc: int, body: bytes):
        a = addr if addr else node.addr
        if fc in (3, 4, 2):
            if len(body) != 4:
                return exception(a, fc, 3)
            start, qty = int.from_bytes(body[:2], "big"), int.from_bytes(body[2:], "big")
            limit = {3: 125, 4: 125, 2: 2000}[fc]
            size = {3: HR_SIZE, 4: IR_SIZE, 2: DI_SIZE}[fc]
            if not 1 <= qty <= limit:
                return exception(a, fc, 3)
            if start + qty > size:
                return exception(a, fc, 2)
            if fc == 2:
                bits = [1 if node.pir else 0][start:start + qty]
                nbytes = (qty + 7) // 8
                data = bytearray(nbytes)
                for i, bit in enumerate(bits):
                    data[i // 8] |= bit << (i % 8)
                return with_crc(bytes([a, fc, nbytes]) + bytes(data))
            regs = node.input_regs() if fc == 4 else list(node.hr)
            payload = b"".join(r.to_bytes(2, "big") for r in regs[start:start + qty])
            return with_crc(bytes([a, fc, len(payload)]) + payload)
        if fc == 6:
            if len(body) != 4:
                return exception(a, fc, 3)
            index, value = int.from_bytes(body[:2], "big"), int.from_bytes(body[2:], "big")
            if index >= HR_SIZE:
                return exception(a, fc, 2)
            if not node.hr_value_ok(index, value):
                return exception(a, fc, 3)
            node.hr[index] = value
            return with_crc(bytes([a, fc]) + body)
        if fc == 16:
            if len(body) < 5:
                return exception(a, fc, 3)
            start, qty, nbytes = int.from_bytes(body[:2], "big"), int.from_bytes(body[2:4], "big"), body[4]
            if not 1 <= qty <= 123 or nbytes != 2 * qty or len(body) != 5 + nbytes:
                return exception(a, fc, 3)
            if start + qty > HR_SIZE:
                return exception(a, fc, 2)
            values = [int.from_bytes(body[5 + 2 * i:7 + 2 * i], "big") for i in range(qty)]
            if not all(node.hr_value_ok(start + i, v) for i, v in enumerate(values)):
                return exception(a, fc, 3)
            for i, v in enumerate(values):
                node.hr[start + i] = v
            return with_crc(bytes([a, fc]) + body[:4])
        return exception(a, fc, 1)


def read_frame(fd: int, gap: float) -> bytes:
    """Une trame RTU = des octets suivis d'un silence. Le silence est généreux (Python n'est pas temps réel)."""
    buf = bytearray()
    while True:
        ready, _, _ = select.select([fd], [], [], gap if buf else None)
        if not ready:
            return bytes(buf)
        data = os.read(fd, 256)
        if not data:
            raise EOFError("port fermé")
        buf += data


def serve(ser: serial.Serial, bus: Bus, gap: float, turnaround: float, verbose: bool) -> None:
    fd = ser.fileno()
    while True:
        frame = read_frame(fd, gap)
        response, node = bus.respond(frame)
        if verbose:
            print(f"< {frame.hex(' ')}", flush=True)
        if response is None:
            continue
        if node is not None:
            if node.fault == "badcrc":
                response = response[:-1] + bytes([response[-1] ^ 0xFF])
            elif node.fault == "slow":
                time.sleep(node.delay_ms / 1000)
        time.sleep(turnaround)
        ser.write(response)
        if verbose:
            print(f"> {response.hex(' ')}", flush=True)


def updater(nodes: dict[int, Node]) -> None:
    while True:
        now = time.monotonic()
        for node in nodes.values():
            if now >= node.next_update:
                node.measure()
        time.sleep(0.05)


def make_control(nodes: dict[int, Node]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code: int, obj) -> None:
            body = json.dumps(obj, indent=1).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/__state":
                return self._reply(200, {a: {"serial": n.serial_no, "fault": n.fault, "hr": n.hr, "pir": n.pir,
                                             "seq": n.seq, "temp_override": n.temp_override}
                                         for a, n in nodes.items()})
            try:
                node = nodes[int(q["slave"])]
            except (KeyError, ValueError):
                return self._reply(404, {"erreur": "paramètre slave inconnu"})
            if url.path == "/__fault":
                if q.get("mode") not in FAULTS:
                    return self._reply(400, {"erreur": f"mode parmi {FAULTS}"})
                node.fault, node.delay_ms = q["mode"], int(q.get("delay_ms", 200))
            elif url.path == "/__temp":
                node.temp_override = None if q.get("value") == "none" else float(q["value"])
                node.measure()
            elif url.path == "/__pir":
                node.pir = q.get("value") == "1"
            elif url.path == "/__reset_config":
                node.hr = list(HR_DEFAULT)
            else:
                return self._reply(404, {"erreur": "route inconnue"})
            self._reply(200, {"ok": True})

    return Handler


def parse_node(text: str, time_scale: float) -> Node:
    parts = text.split(":")
    addr, serial_no = int(parts[0]), int(parts[1])
    if not 1 <= addr <= 247 or not 1 <= serial_no <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(f"nœud invalide : {text}")
    return Node(addr, serial_no, "nopressure" not in parts[2:], time_scale, seed=addr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="port série (un bout de ptylink.py, ou un vrai adaptateur)")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--node", action="append", metavar="ADRESSE:SERIE[:nopressure]",
                    help="un nœud (répétable). Défaut : 1:4096  2:4097  3:4098:nopressure")
    ap.add_argument("--time-scale", type=float, default=1.0, help="accélère les périodes de mesure (20 = 20 fois plus vite)")
    ap.add_argument("--gap-ms", type=float, default=20, help="silence qui termine une trame (RTU réel : 3,5 caractères)")
    ap.add_argument("--turnaround-ms", type=float, default=2, help="délai avant de répondre")
    ap.add_argument("--control-port", type=int, default=8090, help="interface HTTP locale des pannes (0 = aucune)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    nodes = {n.addr: n for n in (parse_node(t, args.time_scale)
                                 for t in (args.node or ["1:4096", "2:4097", "3:4098:nopressure"]))}
    if len(nodes) != len(args.node or [1, 2, 3]):
        sys.exit("adresses d'esclave en double")

    ser = serial.Serial(args.port, args.baud, bytesize=8, parity="N", stopbits=1)
    threading.Thread(target=updater, args=(nodes,), daemon=True).start()
    if args.control_port:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.control_port), make_control(nodes))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"sim_modbus : {len(nodes)} nœuds {sorted(nodes)} sur {args.port} à {args.baud} bauds", flush=True)
    try:
        serve(ser, Bus(nodes), args.gap_ms / 1000, args.turnaround_ms / 1000, args.verbose)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
