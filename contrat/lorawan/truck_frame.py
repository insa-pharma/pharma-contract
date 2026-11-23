"""Codec de référence de la trame LoRaWAN du camion (format v1).

Spécification : voir CONTRAT.md, section « Trame LoRaWAN du camion ».
Le firmware ESP32 (C++) et le décodeur ChirpStack (chirpstack_codec.js) doivent
produire / lire exactement les mêmes octets que ce module. Le fichier
truck_vectors.json (généré par ce module) est le jeu de test commun.

Usage :
    python3 truck_frame.py            # auto-test + (re)génère truck_vectors.json
"""
import json
import struct
from pathlib import Path

VERSION = 1
PORT_BATCH = 10
PORT_HEARTBEAT = 11
MAX_RECORDS_PER_FRAME = 10  # 5 + 10 * 16 = 165 octets <= 222 (DR5)

HEADER = struct.Struct("<BBBBB")  # ver, batch_id, frame_idx, frame_total, count
RECORD = struct.Struct("<IiihBB")  # ts_s, lat_e5, lon_e5, temp_c100, hum_x2, flags
HEARTBEAT = struct.Struct("<BHHI")  # ver, battery_mv, pending_records, uptime_s

NO_FIX = 0x7FFFFFFF
TEMP_INVALID = -0x8000
HUM_INVALID = 0xFF

F_GPS_FIX = 1 << 0
F_GAP_BEFORE = 1 << 1
F_TEMP_ALARM = 1 << 2


def encode_records(records, batch_id):
    """records: liste de dicts bruts {ts_s, lat_e5, lon_e5, temp_c100, hum_x2, flags}.
    Retourne la liste des trames (bytes) à envoyer sur le port 10."""
    chunks = [records[i:i + MAX_RECORDS_PER_FRAME]
              for i in range(0, len(records), MAX_RECORDS_PER_FRAME)]
    frames = []
    for idx, chunk in enumerate(chunks):
        payload = HEADER.pack(VERSION, batch_id & 0xFF, idx, len(chunks), len(chunk))
        for r in chunk:
            payload += RECORD.pack(r["ts_s"], r["lat_e5"], r["lon_e5"],
                                   r["temp_c100"], r["hum_x2"], r["flags"])
        frames.append(payload)
    return frames


def decode_batch(payload):
    ver, batch_id, idx, total, count = HEADER.unpack_from(payload, 0)
    if ver != VERSION:
        raise ValueError(f"version inconnue: {ver}")
    if len(payload) != HEADER.size + count * RECORD.size:
        raise ValueError("longueur incohérente")
    out = {"batch_id": batch_id, "frame_idx": idx, "frame_total": total, "records": []}
    for i in range(count):
        ts_s, lat, lon, temp, hum, flags = RECORD.unpack_from(
            payload, HEADER.size + i * RECORD.size)
        fix = bool(flags & F_GPS_FIX) and lat != NO_FIX and lon != NO_FIX
        out["records"].append({
            "ts_ms": ts_s * 1000,
            "temperature_c": None if temp == TEMP_INVALID else temp / 100,
            "humidity_pct": None if hum == HUM_INVALID else hum / 2,
            "gps_fix": fix,
            "lat": lat / 1e5 if fix else None,
            "lon": lon / 1e5 if fix else None,
            "gap_before": bool(flags & F_GAP_BEFORE),
            "temp_alarm": bool(flags & F_TEMP_ALARM),
        })
    return out


def encode_heartbeat(battery_mv, pending_records, uptime_s):
    return HEARTBEAT.pack(VERSION, battery_mv, pending_records, uptime_s)


def decode_heartbeat(payload):
    ver, battery_mv, pending, uptime = HEARTBEAT.unpack(payload)
    if ver != VERSION:
        raise ValueError(f"version inconnue: {ver}")
    return {"battery_mv": battery_mv, "pending_records": pending, "uptime_s": uptime}


def _selftest():
    base_ts = 1761060000  # 2025-10-21 ~15:20 UTC
    records = []
    for i in range(23):  # 23 -> 3 trames (10 + 10 + 3)
        records.append({
            "ts_s": base_ts + 60 * i,
            "lat_e5": 4708123 + 10 * i,   # 47.08123 N (Bourges)
            "lon_e5": 239456 - 10 * i,    # 2.39456 E
            "temp_c100": 450 + i,         # 4.50 C ...
            "hum_x2": 90 + i,             # 45.0 % ...
            "flags": F_GPS_FIX,
        })
    # cas limites
    records[5].update(lat_e5=NO_FIX, lon_e5=NO_FIX, flags=0)               # pas de fix GPS
    records[6].update(temp_c100=TEMP_INVALID, hum_x2=HUM_INVALID)          # capteur HS
    records[7].update(flags=F_GPS_FIX | F_GAP_BEFORE | F_TEMP_ALARM,
                      temp_c100=-1250)                                     # -12.50 C, alarme
    frames = encode_records(records, batch_id=7)
    assert [len(f) for f in frames] == [165, 165, 53], [len(f) for f in frames]
    assert max(len(f) for f in frames) <= 222

    decoded = [decode_batch(f) for f in frames]
    flat = [r for d in decoded for r in d["records"]]
    assert len(flat) == 23
    assert flat[0]["temperature_c"] == 4.5 and flat[0]["humidity_pct"] == 45.0
    assert flat[5]["gps_fix"] is False and flat[5]["lat"] is None
    assert flat[6]["temperature_c"] is None and flat[6]["humidity_pct"] is None
    assert flat[7]["temperature_c"] == -12.5 and flat[7]["gap_before"] and flat[7]["temp_alarm"]
    assert [d["frame_idx"] for d in decoded] == [0, 1, 2]
    assert all(d["frame_total"] == 3 and d["batch_id"] == 7 for d in decoded)

    hb = encode_heartbeat(3987, 23, 86400)
    assert len(hb) == 9 and decode_heartbeat(hb) == {
        "battery_mv": 3987, "pending_records": 23, "uptime_s": 86400}

    vectors = {
        "batch": [{"port": PORT_BATCH, "hex": f.hex(), "decoded": d}
                  for f, d in zip(frames, decoded)],
        "heartbeat": [{"port": PORT_HEARTBEAT, "hex": hb.hex(),
                       "decoded": decode_heartbeat(hb)}],
    }
    out = Path(__file__).with_name("truck_vectors.json")
    out.write_text(json.dumps(vectors, indent=1) + "\n")
    print("OK: 3 trames", [len(f) for f in frames], "+ heartbeat 9 o ->", out.name)


if __name__ == "__main__":
    _selftest()
