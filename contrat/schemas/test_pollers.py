"""Valide pollers.toml : schéma JSON (types, plages) + règles de cohérence.

Usage : pip install jsonschema && python3 test_pollers.py
Les règles de cohérence ci-dessous sont la référence : le poller Rust doit rejeter les mêmes cas
(les cas invalides de ce fichier serviront de vecteurs de test, comme pour la trame LoRaWAN, D20).
"""
import copy
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).parent
schema = __import__("json").loads((HERE / "pollers.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema)


def coherence_errors(cfg: dict) -> list[str]:
    """Règles que JSON Schema ne sait pas exprimer."""
    errs: list[str] = []
    nodes = cfg["node"]
    for field in ("id", "slave", "serial"):
        vals = [n[field] for n in nodes if field in n]
        dup = {v for v in vals if vals.count(v) > 1}
        if dup:
            errs.append(f"{field} en double : {sorted(dup)}")
    pirs = [n["pir"] for n in nodes if "pir" in n]
    if len(pirs) != len(set(pirs)):
        errs.append("pir en double")
    for n in nodes:
        lo = n.get("temp_min_c", cfg["defaults"]["temp_min_c"])
        hi = n.get("temp_max_c", cfg["defaults"]["temp_max_c"])
        if lo >= hi:
            errs.append(f"{n['id']} : temp_min_c ({lo}) doit être < temp_max_c ({hi}) effectifs")
    return errs


def errors(cfg: dict) -> list[str]:
    errs = [e.message for e in validator.iter_errors(cfg)]
    return errs or coherence_errors(cfg)


example = tomllib.loads((HERE.parent / "examples" / "pollers.example.toml").read_text(encoding="utf-8"))
assert not errors(example), errors(example)


def variant(mutate):
    cfg = copy.deepcopy(example)
    mutate(cfg)
    return cfg


INVALID = {
    "id en double": variant(lambda c: c["node"][1].update(id="env-01")),
    "adresse en double": variant(lambda c: c["node"][1].update(slave=1)),
    "adresse 0 (broadcast)": variant(lambda c: c["node"][0].update(slave=0)),
    "adresse 248": variant(lambda c: c["node"][0].update(slave=248)),
    "série 0": variant(lambda c: c["node"][0].update(serial=0)),
    "série en double": variant(lambda c: c["node"][1].update(serial=4096)),
    "min >= max (surcharge d'un seul côté)": variant(lambda c: c["node"][0].update(temp_min_c=9.0)),
    "faute de frappe sur une clé": variant(lambda c: c["node"][0].update(periode_s=10)),
    "période 0": variant(lambda c: c["defaults"].update(period_s=0)),
    "id en majuscules": variant(lambda c: c["node"][0].update(id="ENV-01")),
    "zone absente": variant(lambda c: c["node"][0].pop("zone")),
    "parité inconnue": variant(lambda c: c["bus"].update(parity="mark")),
    "schema 2": variant(lambda c: c.update(schema=2)),
    "aucun nœud": variant(lambda c: c.update(node=[])),
    "pir en double": variant(lambda c: (c["node"][0].update(pir="pir-01"))),
}
for name, cfg in INVALID.items():
    assert errors(cfg), f"'{name}' devrait être rejeté"

# nœud sans numéro de série : accepté (pas de vérification d'identité, D32)
sans_serie = variant(lambda c: c["node"][0].pop("serial"))
assert not errors(sans_serie)

print(f"OK: exemple valide, {len(INVALID)} cas invalides rejetés, nœud sans série accepté")
