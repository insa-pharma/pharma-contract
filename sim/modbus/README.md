# sim/modbus — faux nœuds Modbus RTU

Remplace les Arduino pendant le développement : sert la table du [contrat §1](../../contrat/CONTRAT.md) sur un port série virtuel, avec plusieurs esclaves et des pannes à la demande. Aucun matériel, pas de `socat`.

| Fichier | Rôle |
|---|---|
| `ptylink.py` | deux ports série virtuels reliés (ce que l'un écrit, l'autre le lit) |
| `sim_modbus.py` | les nœuds : registres, mesures qui évoluent, pannes, interface HTTP de contrôle |
| `test_sim_modbus.py` | test du simulateur en trames brutes, croisé avec `pymodbus` |

Dépendances : `pip install pyserial` (et `pymodbus` pour le croisement facultatif du test).

## Lancer

```bash
# terminal 1 : le câble virtuel
python3 ptylink.py --link-a /tmp/pharma-ttyA --link-b /tmp/pharma-ttyB

# terminal 2 : les Arduino simulés (périodes accélérées 20 fois pour tester vite)
python3 sim_modbus.py --port /tmp/pharma-ttyA --time-scale 20 -v

# le poller ouvre /tmp/pharma-ttyB à 9600 bauds, 8N1
```

Nœuds par défaut (`--node ADRESSE:SERIE[:nopressure]`, répétable) : `1:4096`, `2:4097`, `3:4098:nopressure` — les mêmes numéros de série que `pollers.example.toml`.

## Ce que le simulateur imite

- Fonctions **02, 03, 04, 06, 16**, exceptions 01 (fonction), 02 (adresse), 03 (valeur) ; trame au CRC faux ignorée ; esclave inconnu muet ; diffusion (adresse 0) sans réponse.
- Les écritures de configuration sont validées comme le ferait le firmware : période de 1 à 3600 s, seuils de −50 à +100 °C. Une valeur refusée donne une exception 03 : c'est le cas à gérer côté poller (D28).
- `temp_alarm` (bit 1 du statut) suit les seuils **écrits** dans les registres de maintien.
- Les mesures évoluent à chaque période (registre de maintien 0), la séquence s'incrémente, l'uptime avance.

## Pannes et leviers (HTTP, `127.0.0.1:8090`)

| Appel | Effet |
|---|---|
| `/__fault?slave=1&mode=silent` | le nœud ne répond plus (délai d'attente) |
| `.../mode=invalid` | température `0x8000`, humidité et pression `0xFFFF`, `sensor_ok = 0` |
| `.../mode=frozen` | la séquence n'avance plus (le poller doit passer `sensor_ok` à faux après 3 lectures identiques) |
| `.../mode=badserial` | numéro de série décalé (+1000) → `identity_mismatch` |
| `.../mode=zeroserial` | numéro de série `0` → refus (D32) |
| `.../mode=badcrc` | réponse au CRC faux |
| `.../mode=slow&delay_ms=300` | réponse retardée |
| `.../mode=none` | retour à la normale |
| `/__temp?slave=1&value=9.3` | impose une température (`value=none` pour annuler) → alarme à 9 °C de la démo |
| `/__pir?slave=2&value=1` | détecteur de mouvement actif |
| `/__reset_config?slave=1` | l'Arduino « redémarre » : registres de maintien aux valeurs par défaut (cas `config_drift`) |
| `/__state` | état de tous les nœuds |

## Limites à connaître

- Le silence qui termine une trame est de 20 ms (`--gap-ms`), contre 3,5 caractères (≈ 4 ms à 9600 bauds) sur un vrai bus : Python n'est pas temps réel. Un poller qui passe ici peut encore avoir des soucis de **délais** sur un vrai adaptateur USB-RS485 ; ce sera à valider sur le matériel.
- Un port pty n'a ni bruit, ni collision, ni demi-duplex : les soucis de câblage (A/B inversés, terminaison) ne se reproduisent pas ici.
- Le simulateur et le poller doivent tous deux lire le contrat, pas se copier : en cas de désaccord, c'est le contrat qui tranche.
