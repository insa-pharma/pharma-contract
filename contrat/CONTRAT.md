# Contrat d'interface — v1

Surveillance et traçabilité de produits pharmaceutiques (INSA STI 5A, option 2SEC).

**But :** chaque membre de l'équipe développe son composant **contre ce document et contre un mock**, sans attendre les autres. Un composant est « fini » quand il passe les tests de contrat, qu'il soit réel (`hw`) ou simulé (`sim`).

**Règle de changement :** on ne modifie ce fichier que par une pull request que les propriétaires des composants concernés relisent. Tout changement incompatible incrémente la version (`v: 2`). Les passages à vérifier sur le matériel réel sont marqués **[à vérifier]**.

## 0. Conventions globales

| Sujet | Règle |
|---|---|
| Site | `wh01` (minuscules/chiffres). Prévoir `wh02`… : tout est paramétré par `site` |
| Identifiants | `env-01`, `truck-01`, `reader-01`, `pir-01`, `cam-01`, `rpi5` |
| Temps | **UTC**, `ts` en **millisecondes depuis l'epoch**, instant de la **mesure** (pas de l'arrivée) |
| Synchro horloge | RPi5 : chrony (NTP, GPS du HAT en secours). Camion : heure du GPS embarqué |
| Unités | °C, % d'humidité relative, hPa, degrés décimaux WGS84 |
| Valeur invalide | `null` côté JSON ; valeur sentinelle documentée côté binaire |
| Encodage binaire | **little-endian** (natif ESP32) |

## 1. Terrain : Arduino ↔ RPi5 (Modbus RTU)

**Liaison :** RS485, **9600 bauds, 8N1**. Le RPi5 est le **seul maître**, via l'adaptateur USB-RS485 (`/dev/ttyUSB0`). Le bus accepte **plusieurs nœuds** (par exemple un Arduino par salle) : chaque nœud a sa propre adresse d'esclave (1 à 247, défaut 1) et son `src.id` (`env-01`, `env-02`…), déclarés dans le fichier de configuration du poller. Le poller interroge les nœuds l'un après l'autre ; un échange de 9 registres coûte de l'ordre de 50 ms. Période d'interrogation : 10 s par nœud. Tous les nœuds implémentent **la même table** ci-dessous. *(D29, décidé)* Le bus ne transporte **aucun nom métier** : le fichier de configuration du poller associe chaque adresse à un `src.id` stable et à une `zone` (emplacement), publiée dans le `status` du nœud *(D31, décidé)*. Format de ce fichier : [`schemas/pollers.schema.json`](schemas/pollers.schema.json), exemple dans [`examples/pollers.example.toml`](examples/pollers.example.toml) *(D33)*.

**Registres d'entrée (FC04, lecture seule)** — le maître lit les adresses 0 à 8 en **une seule** requête :

| Adr. | Contenu | Type | Échelle | Invalide |
|---|---|---|---|---|
| 0 | Température | int16 | °C × 100 | `0x8000` |
| 1 | Humidité | uint16 | % × 100 | `0xFFFF` |
| 2 | Pression | uint16 | hPa × 10 | `0xFFFF` (capteur absent) |
| 3 | Statut | uint16 | bit0 `sensor_ok`, bit1 `temp_alarm` | — |
| 4–5 | Uptime | uint32 | s (mot de poids fort en adr. 4) | — |
| 6 | Séquence | uint16 | +1 à chaque mesure, rebouclage à 65535 | — |
| 7–8 | Numéro de série | uint32 | fixé à la programmation de la carte, unique par carte (mot de poids fort en adr. 7) | `0` (non programmé) |

**Entrées discrètes (FC02) :** adresse 0 = détecteur de mouvement PIR (1 = mouvement). *Optionnel : s'il est branché sur l'Arduino.*

**Registres de maintien (FC03/FC06) :** 0 = période d'échantillonnage en s (défaut 10, plage 1–3600) ; 1 = seuil bas en °C × 100 (défaut 200) ; 2 = seuil haut en °C × 100 (défaut 800).

**Règles du poller (RPi5) :**
- si la séquence ne change pas pendant 3 interrogations de suite → `sensor_ok = false` ;
- **vérification d'identité** *(D32)* : si `pollers.toml` indique un numéro de série attendu pour ce nœud et que le registre 7–8 lu est différent (ou vaut `0`), le poller **ne publie pas la télémétrie** de ce nœud, publie une alarme `identity_mismatch` (gravité `critical`) et le signale dans `status`. Le numéro de série détecte une erreur de câblage ou d'adressage ou un appareil de remplacement ; ce n'est **pas** une authentification (n'importe quel appareil sur le bus peut annoncer le même numéro) ;
- erreur Modbus (timeout, CRC) → ne rien publier, incrémenter un compteur d'erreurs, le signaler dans `status` ;
- **écriture limitée à la configuration** *(D28, décidé)* : au démarrage, le poller écrit les registres de maintien (période, seuils) à partir de son fichier de configuration. À chaque cycle, il les relit ; une valeur différente de celle attendue est signalée par `config_drift` dans `status` et par un message `alarm`. Il n'écrit jamais ailleurs.

> Modbus n'a aucune authentification : les registres de maintien sont la surface d'attaque évidente (cible de la Red Team). La version durcie ne change pas ce contrat : elle isole le bus.

## 2. Bus interne : enveloppe et topics MQTT (Mosquitto sur le RPi5)

**Topic :** `pharma/{site}/{src.type}/{src.id}/{kind}` avec `kind ∈ telemetry | event | alarm | status`.

| Exemple de topic | Producteur |
|---|---|
| `pharma/wh01/env/env-01/telemetry` | poller Modbus |
| `pharma/wh01/truck/truck-01/telemetry` | ingestion LoRaWAN |
| `pharma/wh01/access/reader-01/event` | service contrôle d'accès |
| `pharma/wh01/motion/pir-01/event` | poller (entrée discrète) ou ESP32 |
| `pharma/wh01/cam/cam-01/status` | enregistreur vidéo |
| `pharma/wh01/gw/rpi5/status` | chaque service, avec Last Will |

**Exemple (statut d'un nœud Modbus, publié par le poller, retenu) :**
```json
{"v":1,"ts":1761060000000,"site":"wh01","src":{"type":"env","id":"env-01"},
 "kind":"status",
 "data":{"online":true,"zone":"salle-froide-a","slave":1,"serial":4096,"errors":0,"config_drift":false}}
```

- **QoS 1** partout. `retain` uniquement pour `status` (+ Last Will `{"online": false}`).
- Pas de topic de commande en v1 (rien ne pilote le terrain depuis le bus).
- Un seul schéma, validé en CI : [`schemas/envelope.schema.json`](schemas/envelope.schema.json). Exemples valides et invalides : `schemas/test_schemas.py`.

**Exemple (température d'entrepôt) :**
```json
{"v":1,"ts":1761060000000,"site":"wh01","src":{"type":"env","id":"env-01"},
 "kind":"telemetry",
 "data":{"temperature_c":4.52,"humidity_pct":45.1,"pressure_hpa":1013.2,"sensor_ok":true}}
```

**Exemple (accès) :**
```json
{"v":1,"ts":1761060012000,"site":"wh01","src":{"type":"access","id":"reader-01"},
 "kind":"event",
 "data":{"card_id":"a1b2c3d4e5f60718","mode":"challenge","result":"granted","reason":"ok"}}
```

Le **même** contrat sert aux deux versions de l'infrastructure : vulnérable (`1883`, anonyme) et durcie (`8883`, TLS + authentification + ACL par topic). Seule la configuration change.

## 3. Vers le cloud : RPi5 → ThingsBoard

Un service `tb-bridge` s'abonne à `pharma/#` et publie vers ThingsBoard, en MQTT, avec **un seul jeton d'accès** (celui d'un appareil de type *gateway*).

- Nom de l'appareil ThingsBoard : `{site}.{src.id}` (ex. `wh01.env-01`).
- Clés de télémétrie = clés de `data`. Horodatage = `ts` de l'enveloppe.
- Topic MQTT de la *Gateway API* : `v1/gateway/telemetry`, charge utile `{"wh01.env-01":[{"ts":…,"values":{…}}]}` **[à vérifier dans la doc de la version installée]**.
- **File d'attente locale persistante** (SQLite) côté `tb-bridge` : coupure internet = on rejoue au retour, dans l'ordre, sans perte ni doublon.
- Connexion **sortante seulement** (aucun port ouvert vers l'entrepôt depuis internet).
- Les **alarmes de température** sont calculées **une seule fois, dans ThingsBoard** (chaîne de règles), à partir des attributs serveur `temp_min_c = 2.0` et `temp_max_c = 8.0` (chaîne du froid 2–8 °C). Les messages `alarm` du bus sont réservés aux alarmes **locales** (intrusion).
- Modèle d'entités : *Asset* `Entrepôt` et *Asset* `Camion`, reliés à leurs appareils par des relations. Une *Expédition* (futur) sera un asset relié au camion.

## 4. Trame LoRaWAN du camion

### 4.1 Paramètres radio (imposés par le HAT Dragino single-channel)

| Paramètre | Valeur |
|---|---|
| Plan | EU868, classe A |
| Activation | **ABP** (OTAA impossible sans émission descendante) **[à vérifier sur le forwarder]** |
| Canal / débit | **un seul** : 868,1 MHz, **DR5** (SF7, 125 kHz). Les autres canaux du plan doivent être désactivés dans le firmware |
| ADR | désactivé |
| Messages | non confirmés (pas d'accusé de réception) |
| Port 10 | lot de mesures |
| Port 11 | heartbeat |

### 4.2 Port 10 — lot de mesures (taille : 5 + 16·n octets, n ≤ 10, soit ≤ 165 o ≤ 222 o du DR5)

**En-tête (5 octets) :** `version`(u8 = 1) · `batch_id`(u8, +1 à chaque déchargement) · `frame_idx`(u8) · `frame_total`(u8) · `count`(u8).

**Enregistrement (16 octets), répété `count` fois :**

| Offset | Champ | Type | Sens | Invalide |
|---|---|---|---|---|
| 0 | `ts` | u32 | secondes epoch UTC (GPS) | — |
| 4 | `lat` | i32 | degrés × 10⁵ | `0x7FFFFFFF` |
| 8 | `lon` | i32 | degrés × 10⁵ | `0x7FFFFFFF` |
| 12 | `temp` | i16 | °C × 100 | `0x8000` |
| 14 | `hum` | u8 | % × 2 (pas de 0,5 %) | `0xFF` |
| 15 | `flags` | u8 | bit0 `gps_fix`, bit1 `gap_before`, bit2 `temp_alarm` | — |

`gap_before` = des mesures ont été perdues (mémoire pleine) juste avant celle-ci.

### 4.3 Port 11 — heartbeat (9 octets)

`version`(u8) · `battery_mv`(u16) · `pending_records`(u16) · `uptime_s`(u32). Envoyé toutes les 10 minutes quand le camion est à portée.

### 4.4 Règles d'envoi

- Le camion enregistre une mesure toutes les 60 s (configurable) dans la flash. **Rien n'est jamais perdu silencieusement** : si la mémoire est pleine, on écrase le plus ancien et on lève `gap_before` sur le suivant.
- Dès qu'il est à portée, il décharge les lots dans l'ordre. Chaque trame est envoyée **une seule fois**. Le serveur détecte les trous grâce à `frame_idx/frame_total` et au compteur de trames `fCnt`.
- **Duty cycle 1 % (EU868) :** une trame de 165 o prend environ 0,3 s d'antenne **[à confirmer avec un calculateur d'airtime]**, donc **au moins ~30 s entre deux trames**. Ordre de grandeur : 2 h de trajet à 1 mesure/min = 120 mesures = 12 trames ≈ 6 min de déchargement.
- **Compteur de trames :** écrit en mémoire non volatile (NVS) tous les 10 envois, et repris à `valeur + 10` après un redémarrage. Sinon le serveur rejette le camion comme un rejeu.
- Le serveur **déduplique** par `(dev_eui, ts)` : un ré-envoi futur ne crée pas de doublon.

### 4.5 Côté ChirpStack

- Profil d'appareil `esp32-abp-eu868`. Le codec JavaScript [`lorawan/chirpstack_codec.js`](lorawan/chirpstack_codec.js) est **facultatif** : il sert seulement à afficher les données décodées dans l'interface de ChirpStack.
- Le service `lora-ingest` lit les événements d'uplink ChirpStack (topic MQTT du type `application/{app_id}/device/{dev_eui}/event/up`) et **décode lui-même** la charge utile déjà déchiffrée par ChirpStack, fournie en base64 dans `data` **[à vérifier : champs exacts de la version installée]**. Pour chaque enregistrement, il publie un message `truck/telemetry` sur le bus (`rx` = heure d'arrivée de l'uplink).
- Codec de référence, vecteurs de test communs et test de non-régression : `lorawan/truck_frame.py`, `lorawan/truck_vectors.json`, `lorawan/test_codec.js`. Le firmware ESP32 doit produire exactement les mêmes octets que `truck_vectors.json`.

## 5. Contrôle d'accès : carte JavaCard ↔ lecteur (APDU ISO 7816)

**AID de l'applet :** `F0 50 48 41 52 4D 41 01` (propriétaire).

| Commande | APDU | Réponse |
|---|---|---|
| SELECT | `00 A4 04 00 08 <AID>` | `90 00` |
| GET_CARD_ID | `80 10 00 00 08` | 8 octets `card_id` + `90 00` |
| VERIFY_PIN | `00 20 00 01 04 <4 chiffres ASCII>` | `90 00`, `63 Cx` (x essais restants), `69 83` (carte bloquée) |
| INTERNAL_AUTH | `80 20 00 00 20 <défi 32 o> 00` | signature + `90 00` |

- **Défi :** 16 octets aléatoires du lecteur ‖ identifiant du lecteur (`reader-01`, complété à 16 octets). La carte signe `SHA-256(défi ‖ card_id)`.
- **Algorithme :** ECDSA P-256 si la carte le supporte, sinon AES-CMAC. **Choix à trancher par la personne JavaCard** : l'interface ci-dessus ne change pas.
- Autres mots d'état : `6D 00` instruction inconnue, `6E 00` classe inconnue, `69 85` conditions non remplies.

**Deux modes (même applet, même événement) :**
- `uid` (version vulnérable) : le lecteur lit seulement `card_id` et fait confiance. La carte est clonable.
- `challenge` (version durcie) : GET_CARD_ID puis INTERNAL_AUTH. Le lecteur vérifie la signature avec la clé publique enrôlée.

**Décision locale (hors ligne) :** le service lit une base locale `cards(card_id, pubkey, enabled)`. Pas de dépendance internet pour ouvrir la porte. Correspondance vers `reason` : id absent → `unknown_card`, `enabled=0` → `disabled`, signature fausse → `bad_signature`, `69 83` → `pin_blocked`, `63 Cx` → `bad_pin`, pas de réponse → `timeout`, autre état → `card_error`.

## 6. Vidéo : ESP32-CAM ↔ RPi5

Le RPi5 **tire** le flux (la caméra n'est jamais jointe depuis l'extérieur).

- Instantané : `GET http://cam-01.lan/capture` (JPEG). Flux : `GET http://cam-01.lan:81/stream` (MJPEG multipart, `Content-Type: multipart/x-mixed-replace;boundary=123456789000000000000987654321`, un en-tête `X-Timestamp` par image). Ce sont les valeurs du firmware d'exemple *CameraWebServer* d'Espressif (le flux est sur le port du serveur principal + 1), relues dans son code source ; à reconfirmer si vous utilisez un autre firmware.
- Enregistrement : l'enregistreur découpe le flux en segments de 5 min sous `/var/lib/pharma/video/{cam}/{AAAA}/{MM}/{JJ}/{HHMMSS}.mkv` (rétention 7 jours). Un événement `motion` conserve les segments voisins au-delà de la rétention.
- Mock : [`sim/cam/esp32cam_mock.py`](../sim/cam/esp32cam_mock.py) sert ces mêmes URL (ports 8080/8081 par défaut). Le test [`sim/cam/test_cam_contract.py`](../sim/cam/test_cam_contract.py) passe à l'identique contre le mock et contre la vraie carte.

## 7. Qui livre quoi, et avec quel mock

| Composant | Propriétaire | Produit | Consomme | Mock fourni (profil `sim`) | Test d'acceptation |
|---|---|---|---|---|---|
| Arduino + shield | personne Arduino | registres Modbus (§1) | — | nœuds RTU simulés [`sim/modbus/`](../sim/modbus) | le poller lit les 9 registres sans erreur pendant 1 h |
| Poller Modbus, bus MQTT, `tb-bridge` | RPi5 | messages §2, §3 | §1 | — | messages valides au schéma, coupure internet rejouée sans doublon |
| ESP32 camion | 2 personnes mobilité | trames §4 | — | `sim-truck` (rejoue un trajet GPS) | les octets sont identiques à `truck_vectors.json` |
| Ingestion LoRaWAN | RPi5 | `truck/telemetry` | §4 | uplinks injectés dans ChirpStack | 23 mesures de test reconstituées, pas de doublon |
| Applet JavaCard | personne JavaCard | APDU §5 | — | simulateur de carte **[à vérifier : jCardSim ou lecteur virtuel]** | séquence SELECT → ID → AUTH passante |
| Lecteur / décision locale | à répartir (JavaCard ou RPi5) | `access/event` | §5 | `sim-reader` (cartes fictives) | 7 cas de `reason` couverts |
| Caméra | mobilité n°2 (après réception) | flux §6 | — | `sim-cam` | segments de 5 min écrits, rétention appliquée |
| ThingsBoard | personne serveur | tableaux de bord, règles d'alarme | §3 | instance Docker locale | une alarme se déclenche à 9 °C |
| WAN / RPi3 | personne WAN | réseau, pare-feu | — | — | le RPi5 atteint le cloud, la caméra non |

Intégration : `docker compose --profile sim up` lance tous les mocks et la chaîne complète sans aucun matériel. `--profile hw` remplace progressivement chaque mock par le vrai composant.
