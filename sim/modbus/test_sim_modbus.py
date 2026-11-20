#!/usr/bin/env python3
"""Test du faux esclave Modbus : lance ptylink + sim_modbus, parle en trames brutes.

Usage : pip install pyserial && python3 test_sim_modbus.py
Le client ci-dessous est écrit indépendamment du simulateur (CRC recalculé à part), et un
croisement facultatif avec pymodbus vérifie que les trames sont du Modbus RTU standard.
"""
import json
import os
import select
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import serial

HERE = Path(__file__).parent
CONTROL = 18090  # port de contrôle HTTP de ce test


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes([crc & 0xFF, crc >> 8])


# Vecteur classique de la littérature Modbus : lire 10 registres de maintien de l'esclave 1.
assert crc16(bytes.fromhex("01 03 00 00 00 0A")) == bytes.fromhex("C5 CD"), "CRC16 faux"
# Notre requête du contrat : esclave 1, FC04, adresse 0, 9 registres.
assert crc16(bytes.fromhex("01 04 00 00 00 09")) == bytes.fromhex("30 0C")


class Client:
    def __init__(self, port: str):
        self.ser = serial.Serial(port, 9600, timeout=0.05)

    def call(self, body: bytes, timeout: float = 0.5, corrupt_crc: bool = False) -> bytes | None:
        frame = body + crc16(body)
        if corrupt_crc:
            frame = frame[:-1] + bytes([frame[-1] ^ 0xFF])
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        fd, buf, deadline = self.ser.fileno(), bytearray(), time.monotonic() + timeout
        while True:
            wait = 0.05 if buf else max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([fd], [], [], wait)
            if not ready:
                break
            buf += os.read(fd, 256)
        return bytes(buf) if buf else None

    def read(self, slave: int, fc: int, start: int, qty: int):
        return self.call(bytes([slave, fc]) + start.to_bytes(2, "big") + qty.to_bytes(2, "big"))


def check_crc(resp: bytes) -> bytes:
    assert resp and crc16(resp[:-2]) == resp[-2:], f"CRC de réponse faux : {resp and resp.hex(' ')}"
    return resp[:-2]


def words(resp: bytes) -> list[int]:
    body = check_crc(resp)
    assert body[1] < 0x80, f"exception inattendue : {resp.hex(' ')}"
    return [int.from_bytes(body[3 + 2 * i:5 + 2 * i], "big") for i in range(body[2] // 2)]


def exc_code(resp: bytes) -> int:
    body = check_crc(resp)
    assert body[1] & 0x80, f"exception attendue : {resp.hex(' ')}"
    return body[2]


def control(path: str) -> dict:
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CONTROL}{path}", timeout=2).read())


def main() -> None:
    tmp = tempfile.mkdtemp()
    link_a, link_b = f"{tmp}/ttyA", f"{tmp}/ttyB"
    procs = [subprocess.Popen([sys.executable, str(HERE / "ptylink.py"), "--link-a", link_a, "--link-b", link_b],
                              stdout=subprocess.DEVNULL)]
    try:
        for _ in range(50):
            if os.path.islink(link_a) and os.path.islink(link_b):
                break
            time.sleep(0.1)
        procs.append(subprocess.Popen([sys.executable, str(HERE / "sim_modbus.py"), "--port", link_a,
                                       "--time-scale", "20", "--control-port", str(CONTROL)],
                                      stdout=subprocess.DEVNULL))
        for _ in range(50):
            try:
                control("/__state")
                break
            except OSError:
                time.sleep(0.1)
        cli = Client(link_b)

        # 1. lecture nominale du nœud 1
        r = words(cli.read(1, 4, 0, 9))
        assert len(r) == 9
        temp, hum, press, status, up_hi, up_lo, seq, ser_hi, ser_lo = r
        assert 300 <= temp <= 600, f"température hors plage : {temp / 100}"
        assert 4000 <= hum <= 5000 and 10000 <= press <= 10300
        assert status & 1 == 1, "sensor_ok attendu"
        assert (ser_hi << 16) | ser_lo == 4096
        assert (words(cli.read(2, 4, 0, 9))[7:] == [0, 4097])
        assert words(cli.read(3, 4, 0, 9))[2] == 0xFFFF, "nœud 3 sans capteur de pression"

        # 2. la séquence avance (période 10 s / 20 = 0,5 s)
        time.sleep(1.2)
        assert words(cli.read(1, 4, 0, 9))[6] > seq, "la séquence devrait avancer"

        # 3. registres de maintien : défauts, écriture, validation
        assert words(cli.read(1, 3, 0, 3)) == [10, 200, 800]
        assert cli.call(bytes([1, 6, 0, 1, 0x01, 0x2C])).hex() == (bytes([1, 6, 0, 1, 1, 0x2C]) + crc16(bytes([1, 6, 0, 1, 1, 0x2C]))).hex()
        assert words(cli.read(1, 3, 0, 3)) == [10, 300, 800]
        fc16 = bytes([1, 16, 0, 1, 0, 2, 4]) + (250).to_bytes(2, "big") + (900).to_bytes(2, "big")
        assert check_crc(cli.call(fc16)) == bytes([1, 16, 0, 1, 0, 2])
        assert words(cli.read(1, 3, 0, 3)) == [10, 250, 900]
        assert exc_code(cli.call(bytes([1, 6, 0, 0, 0, 0]))) == 3, "période 0 refusée"
        assert exc_code(cli.call(bytes([1, 6, 0, 5, 0, 1]))) == 2, "adresse 5 inexistante"
        assert words(cli.read(1, 3, 0, 3)) == [10, 250, 900], "une écriture refusée ne change rien"

        # 4. erreurs de protocole
        assert exc_code(cli.read(1, 4, 7, 5)) == 2, "lecture au-delà du registre 8"
        assert exc_code(cli.read(1, 4, 0, 0)) == 3, "quantité 0"
        assert exc_code(cli.call(bytes([1, 0x2B, 0, 0, 0, 0]))) == 1, "fonction inconnue"
        assert cli.read(9, 4, 0, 9) is None, "esclave inexistant : silence"
        assert cli.call(bytes([1, 4, 0, 0, 0, 9]), corrupt_crc=True) is None, "CRC faux : silence"
        assert cli.call(bytes([0, 6, 0, 1, 0, 0x64])) is None, "diffusion : pas de réponse"
        assert words(cli.read(1, 3, 0, 3))[1] == 100 and words(cli.read(2, 3, 0, 3))[1] == 100, "diffusion appliquée"

        # 5. détecteur de mouvement (FC02)
        assert check_crc(cli.read(2, 2, 0, 1)) == bytes([2, 2, 1, 0])
        control("/__pir?slave=2&value=1")
        assert check_crc(cli.read(2, 2, 0, 1)) == bytes([2, 2, 1, 1])

        # 6. alarme locale selon les seuils écrits
        control("/__reset_config?slave=1")
        assert words(cli.read(1, 3, 0, 3)) == [10, 200, 800], "redémarrage de l'Arduino : défauts"
        control("/__temp?slave=1&value=9.3")
        assert words(cli.read(1, 4, 0, 9))[3] & 2 == 2, "temp_alarm au-dessus de 8 °C"
        control("/__temp?slave=1&value=none")

        # 7. pannes
        control("/__fault?slave=1&mode=silent")
        assert cli.read(1, 4, 0, 9) is None
        control("/__fault?slave=1&mode=none")
        assert words(cli.read(1, 4, 0, 9))
        control("/__fault?slave=1&mode=invalid")
        time.sleep(0.8)
        r = words(cli.read(1, 4, 0, 9))
        assert r[0] == 0x8000 and r[1] == 0xFFFF and r[2] == 0xFFFF and r[3] & 1 == 0, "valeurs invalides"
        control("/__fault?slave=1&mode=frozen")
        time.sleep(0.8)
        a = words(cli.read(1, 4, 0, 9))[6]
        time.sleep(1.2)
        assert words(cli.read(1, 4, 0, 9))[6] == a, "séquence figée"
        control("/__fault?slave=1&mode=badserial")
        assert words(cli.read(1, 4, 0, 9))[7:] == [0, 5096]
        control("/__fault?slave=1&mode=zeroserial")
        assert words(cli.read(1, 4, 0, 9))[7:] == [0, 0]
        control("/__fault?slave=1&mode=badcrc")
        resp = cli.read(1, 4, 0, 9)
        assert resp and crc16(resp[:-2]) != resp[-2:], "CRC de réponse volontairement faux"
        control("/__fault?slave=1&mode=slow&delay_ms=300")
        t0 = time.monotonic()
        assert cli.call(bytes([1, 4, 0, 0, 0, 9]), timeout=1.0) is not None
        assert time.monotonic() - t0 >= 0.3, "réponse retardée"
        control("/__fault?slave=1&mode=none")

        # 8. croisement facultatif avec pymodbus (autre implémentation du protocole)
        cli.ser.close()
        try:
            from pymodbus.client import ModbusSerialClient
            pm = ModbusSerialClient(port=link_b, baudrate=9600, timeout=1)
            pm.connect()
            rr = pm.read_input_registers(0, count=9, device_id=2)
            assert not rr.isError() and rr.registers[7:] == [0, 4097], rr
            pm.close()
            cross = "pymodbus : OK"
        except ImportError:
            cross = "pymodbus absent : croisement ignoré"
        except TypeError as exc:
            cross = f"pymodbus : API différente, croisement ignoré ({exc})"

        print(f"TOUT PASSE ({cross})")
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in procs:
            p.wait(timeout=3)


if __name__ == "__main__":
    main()
