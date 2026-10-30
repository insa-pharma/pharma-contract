#!/usr/bin/env python3
"""Exporte les cas de test_pollers.py en fichiers TOML, pour que le poller Rust (ou tout autre
langage) vérifie exactement les mêmes cas que le test Python (D20).

Usage : python3 export_pollers_vectors.py  →  ../vectors/pollers/{valid,invalid}/*.toml + index.json
Chaque fichier est relu et revalidé après écriture : un export qui diverge fait échouer le script.
"""
import json
import re
import shutil
import tomllib
from pathlib import Path

import test_pollers as t  # exécute les tests au passage

OUT = Path(__file__).parent.parent / "vectors" / "pollers"


def scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(v, ensure_ascii=False)


def to_toml(cfg: dict) -> str:
    out = []
    for k, v in cfg.items():
        if v == []:
            out.append(f"{k} = []")  # doit rester avant les tables
        elif not isinstance(v, (dict, list)):
            out.append(f"{k} = {scalar(v)}")
    for k, v in cfg.items():
        if isinstance(v, dict):
            out += ["", f"[{k}]"] + [f"{kk} = {scalar(vv)}" for kk, vv in v.items()]
        elif isinstance(v, list):
            for item in v:
                out += ["", f"[[{k}]]"] + [f"{kk} = {scalar(vv)}" for kk, vv in item.items()]
    return "\n".join(out) + "\n"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower().replace("œ", "oe").replace("é", "e").replace("ô", "o").replace("è", "e").replace("ë", "e"))
    return s.strip("_")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "valid").mkdir(parents=True)
    (OUT / "invalid").mkdir()
    index = []
    cases = [("valid", "exemple", t.example, None), ("valid", "nœud sans série", t.sans_serie, None)]
    cases += [("invalid", name, cfg, t.errors(cfg)[0]) for name, cfg in t.INVALID.items()]
    for kind, name, cfg, reason in cases:
        rel = f"{kind}/{slug(name)}.toml"
        header = f"# {name}\n# attendu : {'accepté' if kind == 'valid' else 'rejeté'}"
        if reason:
            header += f" — {reason}"
        (OUT / rel).write_text(header + "\n\n" + to_toml(cfg), encoding="utf-8")
        again = tomllib.loads((OUT / rel).read_text(encoding="utf-8"))
        assert again == cfg, f"{rel} : l'export diffère du cas d'origine"
        assert bool(t.errors(again)) == (kind == "invalid"), f"{rel} : verdict différent après export"
        index.append({"file": rel, "expected": "accept" if kind == "valid" else "reject", "case": name,
                      "reason": reason})
    (OUT / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(index)} vecteurs exportés dans {OUT}")


if __name__ == "__main__":
    main()
