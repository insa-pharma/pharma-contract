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


## Utilisation de mbpoll avec l'esclave Modbus RTU Arduino

Ce document décrit les quatre commandes utilisées pour tester l'esclave Modbus RTU
(Arduino Uno + shield MFS + capteur LM35 + MAX485) depuis un PC Linux, via un
convertisseur USB-RS485.

Le PC joue le rôle du **maître** Modbus. L'Arduino est l'**esclave** (adresse 1).

### Prérequis

- Montage câblé : Arduino ↔ MAX485 ↔ paire A/B ↔ convertisseur USB-RS485 ↔ PC.
- Arduino alimenté (par son USB) avec le firmware chargé.
- `mbpoll` installé :

```bash
sudo dnf install mbpoll
```

Paramètres de liaison (identiques des deux côtés) : **9600 bauds, 8N1, esclave 1**.

### 1. Repérer le port du convertisseur

```bash
ls /dev/ttyUSB*
```

Liste les ports série USB. Le convertisseur USB-RS485 (puce CH340) apparaît en
général sous `/dev/ttyUSB0`.

> Ne pas confondre avec `/dev/ttyACM0`, qui est l'Arduino Uno lui-même (câble USB
> de programmation). `mbpoll` doit viser le convertisseur.

### 2. Autoriser l'accès au port série

```bash
sudo usermod -aG dialout $USER
```

Ajoute l'utilisateur courant au groupe `dialout`, qui donne le droit d'utiliser les
ports série sans `sudo`. À faire **une seule fois**, puis **fermer la session et se
reconnecter** pour que ce soit pris en compte. Sans cela, `mbpoll` répond
« permission denied ».

### 3. Écrire les seuils d'alarme

```bash
mbpoll -m rtu -a 1 -b 9600 -P none -t 4 -r 2 /dev/ttyUSB0 200 2600
```

Écrit deux valeurs dans les **registres de maintien** (les réglages) :

| Valeur | Registre (Modbus) | Réglage | Signification |
|---|---|---|---|
| `200` | adresse 1 | Seuil bas | 2,00 °C |
| `2600` | adresse 2 | Seuil haut | 26,00 °C |

`mbpoll` écrit les valeurs dans des registres consécutifs à partir de `-r 2`
(adresse 1 en numérotation Modbus). Les températures sont en °C × 100.

Après cette commande, le bit d'alarme est à 1 quand la température sort de
l'intervalle 2 °C – 26 °C.

> Les seuils ne sont pas mémorisés par l'Arduino : ils reviennent à 2 °C / 8 °C à
> chaque redémarrage de la carte. Il faut les réécrire après un reset.

### 4. Lire les mesures en continu

```bash
mbpoll -m rtu -a 1 -b 9600 -P none -t 3 -r 1 -c 9 -l 2000 /dev/ttyUSB0
```

Lit en boucle les 9 **registres d'entrée** (lecture seule), toutes les 2 secondes.
Arrêt avec **Ctrl+C**.

Exemple de sortie :

```
[1]:    2663
[2]:    65535 (-1)
[3]:    65535 (-1)
[4]:    3
[5]:    0
[6]:    218
[7]:    22
[8]:    0
[9]:    1
```

| mbpoll | Adresse | Contenu | Lecture |
|---|---|---|---|
| `[1]` | 0 | Température | 2663 → 26,63 °C (valeur ÷ 100) |
| `[2]` | 1 | Humidité | 65535 = invalide (pas de capteur) |
| `[3]` | 2 | Pression | 65535 = invalide (pas de capteur) |
| `[4]` | 3 | Statut | bit 0 = capteur OK, bit 1 = alarme de température |
| `[5]`, `[6]` | 4–5 | Uptime | secondes depuis le démarrage (poids fort, puis poids faible) |
| `[7]` | 6 | Séquence | +1 à chaque nouvelle mesure |
| `[8]`, `[9]` | 7–8 | Numéro de série | 0 puis 1 → numéro 1 |

Valeurs du statut (`[4]`) :

| Valeur | Sens |
|---|---|
| 1 | capteur OK, pas d'alarme |
| 3 | capteur OK, alarme active |
| 0 | capteur illisible |

L'Arduino ne mesure que toutes les 10 secondes par défaut : la température et la
séquence ne changent donc qu'à ce rythme, alors que l'uptime avance à chaque lecture.

### Explication des options

| Option | Rôle |
|---|---|
| `-m rtu` | Mode Modbus RTU (liaison série) |
| `-a 1` | Adresse de l'esclave (1 à 247) |
| `-b 9600` | Vitesse en bauds |
| `-P none` | Parité : aucune (8N1). Sans cette option, `mbpoll` utilise la parité paire |
| `-t 3` / `-t 4` | Type de registre : `3` = entrée (lecture seule), `4` = maintien (réglages) |
| `-r N` | Premier registre, numéroté à partir de 1 (`-r 1` = adresse 0) |
| `-c N` | Nombre de registres à lire |
| `-l ms` | Intervalle entre deux lectures, en millisecondes |
| `-1` | Une seule lecture (non utilisé ici) |
| valeur(s) en fin de commande | Présentes : écriture. Absentes : lecture |
