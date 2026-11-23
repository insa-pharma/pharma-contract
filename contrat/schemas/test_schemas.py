"""Valide l'enveloppe JSON contre des exemples valides et invalides.

Usage : pip install jsonschema && python3 test_schemas.py
Les mêmes exemples servent de modèle aux mocks (sim-modbus, faux camion, ...)
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).parent
schema = json.loads((HERE / "envelope.schema.json").read_text())
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema)

TS = 1761060000000

VALID = {
    "env telemetry": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                      "kind": "telemetry",
                      "data": {"temperature_c": 4.52, "humidity_pct": 45.1, "pressure_hpa": 1013.2,
                               "sensor_ok": True}},
    "truck telemetry": {"v": 1, "ts": TS, "rx": TS + 90000, "site": "wh01",
                        "src": {"type": "truck", "id": "truck-01"}, "kind": "telemetry",
                        "data": {"temperature_c": 5.1, "humidity_pct": 44.0, "gps_fix": True,
                                 "lat": 47.08123, "lon": 2.39456, "gap_before": False,
                                 "dev_eui": "70b3d57ed0000001", "fcnt": 42}},
    "truck sans fix": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "truck", "id": "truck-01"},
                       "kind": "telemetry",
                       "data": {"temperature_c": None, "humidity_pct": None, "gps_fix": False,
                                "lat": None, "lon": None}},
    "access granted": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "access", "id": "reader-01"},
                       "kind": "event",
                       "data": {"card_id": "a1b2c3d4e5f60718", "mode": "challenge",
                                "result": "granted", "reason": "ok"}},
    "motion": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "motion", "id": "pir-01"},
               "kind": "event", "data": {"active": True}},
    "status LWT": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "gw", "id": "rpi5"},
                   "kind": "status", "data": {"online": False}},
    "status nœud Modbus": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                           "kind": "status",
                           "data": {"online": True, "zone": "salle-froide-a", "slave": 1,
                                    "serial": 4096, "errors": 0, "config_drift": False}},
    "alarme identité": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                        "kind": "alarm",
                        "data": {"rule": "identity_mismatch", "severity": "critical",
                                 "message": "série lu 8192, attendu 4096"}},
    "alarm": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
              "kind": "alarm",
              "data": {"rule": "temp_high", "severity": "critical", "value": 9.3, "threshold": 8.0}},
}

INVALID = {
    "ts en secondes": {"v": 1, "ts": 1761060000, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                       "kind": "telemetry", "data": {"temperature_c": 4, "humidity_pct": 40}},
    "humidité > 100": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                       "kind": "telemetry", "data": {"temperature_c": 4, "humidity_pct": 140}},
    "champ inconnu": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                      "kind": "telemetry",
                      "data": {"temperature_c": 4, "humidity_pct": 40, "temp": 4}},
    "mauvais kind pour access": {"v": 1, "ts": TS, "site": "wh01",
                                 "src": {"type": "access", "id": "reader-01"}, "kind": "telemetry",
                                 "data": {"card_id": "a1b2c3d4e5f60718", "mode": "uid",
                                          "result": "granted", "reason": "ok"}},
    "card_id trop court": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "access", "id": "reader-01"},
                           "kind": "event",
                           "data": {"card_id": "a1b2", "mode": "uid", "result": "granted", "reason": "ok"}},
    "esclave Modbus 0 (broadcast)": {"v": 1, "ts": TS, "site": "wh01",
                                     "src": {"type": "env", "id": "env-01"}, "kind": "status",
                                     "data": {"online": True, "slave": 0}},
    "zone dans la télémétrie": {"v": 1, "ts": TS, "site": "wh01",
                                "src": {"type": "env", "id": "env-01"}, "kind": "telemetry",
                                "data": {"temperature_c": 4, "humidity_pct": 40, "zone": "salle-a"}},
    "numéro de série 0": {"v": 1, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                          "kind": "status", "data": {"online": True, "serial": 0}},
    "version 2": {"v": 2, "ts": TS, "site": "wh01", "src": {"type": "env", "id": "env-01"},
                  "kind": "telemetry", "data": {"temperature_c": 4, "humidity_pct": 40}},
}

for name, msg in VALID.items():
    errs = list(validator.iter_errors(msg))
    assert not errs, f"'{name}' devrait être valide: {errs[0].message}"
for name, msg in INVALID.items():
    assert list(validator.iter_errors(msg)), f"'{name}' devrait être rejeté"

# sortie du décodeur camion -> enveloppe (chaque enregistrement devient un message)
vectors = json.loads((HERE.parent / "lorawan" / "truck_vectors.json").read_text())
n = 0
for frame in vectors["batch"]:
    for rec in frame["decoded"]["records"]:
        msg = {"v": 1, "ts": rec["ts_ms"], "site": "wh01", "src": {"type": "truck", "id": "truck-01"},
               "kind": "telemetry",
               "data": {k: rec[k] for k in ("temperature_c", "humidity_pct", "gps_fix", "lat", "lon",
                                            "gap_before", "temp_alarm")}}
        errs = list(validator.iter_errors(msg))
        assert not errs, errs[0].message
        n += 1
print(f"OK: {len(VALID)} exemples valides, {len(INVALID)} invalides rejetés, "
      f"{n} enregistrements camion convertis et valides")
