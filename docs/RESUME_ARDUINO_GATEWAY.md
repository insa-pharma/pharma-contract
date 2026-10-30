# Arduino ↔ passerelle : ce qu'il faut savoir

Résumé pour la partie Arduino. La référence reste le [contrat d'interface](../contrat/CONTRAT.md) §1 (si ce résumé et le contrat divergent, c'est le contrat qui a raison).

## 1. Vue d'ensemble

```
 Arduino + BME280 (+ PIR)          Passerelle RPi5                          Cloud
 ─────────────────────────         ───────────────────────────────────      ─────────────
 mesure, calcule l'alarme   RS485  poller Modbus ──► Mosquitto (MQTT) ──►   ThingsBoard
 locale, répond au maître  ◄─────► (seul maître)        │                   (tableaux de
                          Modbus                        └─► recorder, ...    bord, alertes)
                            RTU
```

- L'Arduino est un **esclave Modbus RTU** : il ne parle jamais le premier. Il mesure, range le résultat dans des registres, et répond quand on l'interroge.
- Le RPi5 est le **seul maître** du bus. Il interroge chaque nœud à tour de rôle, transforme les registres en messages JSON (« enveloppe » du contrat) et les publie sur MQTT. L'Arduino ne connaît ni MQTT, ni JSON, ni ThingsBoard.
- **Plusieurs Arduino** peuvent partager le même bus (par exemple un par salle). Tous implémentent **exactement la même table de registres** ; seule l'adresse d'esclave (1 à 247) et le numéro de série changent.

## 2. La liaison

RS485 (deux fils A/B en multi-drop, demi-duplex), **9600 bauds, 8N1** (la norme Modbus propose 8E1 par défaut, nous avons choisi 8N1 : les deux côtés doivent être alignés). Une trame = adresse + fonction + données + CRC16 (octet faible d'abord). La fin de trame est détectée par un silence d'au moins 3,5 caractères (environ 4 ms à 9600 bauds).

Le poller interroge un nœud environ toutes les 10 s ; un échange de 9 registres dure de l'ordre de 50 ms. Un nœud qui ne répond pas dans un délai court (de l'ordre de 300 ms) est marqué en erreur, sans bloquer les autres.

## 3. Ce que l'Arduino doit exposer

**Registres d'entrée (FC04, lecture seule)** : le maître lit les adresses 0 à 8 en une seule requête.

| Adr. | Contenu | Type | Échelle | Valeur invalide |
|---|---|---|---|---|
| 0 | Température | int16 | °C × 100 (4,52 °C → 452) | `0x8000` |
| 1 | Humidité | uint16 | % × 100 | `0xFFFF` |
| 2 | Pression | uint16 | hPa × 10 | `0xFFFF` (capteur absent) |
| 3 | Statut | uint16 | bit0 `sensor_ok`, bit1 `temp_alarm` | — |
| 4–5 | Uptime | uint32 | secondes, **poids fort en adr. 4** | — |
| 6 | Séquence | uint16 | +1 à chaque nouvelle mesure, rebouclage à 65535 | — |
| 7–8 | **Numéro de série** | uint32 | fixé à la programmation, unique par carte, **poids fort en adr. 7** | `0` = non programmé |

Les registres Modbus sont en gros-boutiste (octet de poids fort d'abord) sur le fil, quelle que soit l'architecture du microcontrôleur.

**Entrée discrète (FC02) :** adresse 0 = détecteur de mouvement PIR (1 = mouvement). Optionnel, seulement s'il est branché.

**Registres de maintien (FC03 lecture, FC06/FC16 écriture) :** ce sont les réglages que le maître écrit.

| Adr. | Contenu | Défaut | Plage |
|---|---|---|---|
| 0 | Période d'échantillonnage (s) | 10 | 1–3600 |
| 1 | Seuil bas (°C × 100) | 200 | — |
| 2 | Seuil haut (°C × 100) | 800 | — |

Comportements attendus :
- `temp_alarm` (bit 1 du statut) est calculé **par l'Arduino** à partir des seuils courants.
- La séquence ne doit avancer que lorsqu'une **nouvelle mesure** est faite. Si elle reste figée 3 interrogations de suite, le poller considère le capteur en panne : c'est la façon dont il détecte un Arduino « planté mais qui répond encore ».
- Capteur illisible : `sensor_ok = 0` et valeurs invalides (`0x8000` / `0xFFFF`), jamais une ancienne valeur présentée comme fraîche.
- Au démarrage, l'Arduino prend les valeurs par défaut. Pas besoin de stocker les réglages en EEPROM : le poller les réécrit au démarrage de la passerelle et les relit à chaque cycle.
- Écriture invalide (période 0, par exemple) : répondre par une exception Modbus (code 03 « valeur invalide »). *Ce point n'est pas dans le contrat ; le simulateur le fait ainsi, à confirmer ensemble.*

## 4. Pourquoi un numéro de série

Le bus ne transporte aucun nom métier : l'Arduino ne sait pas qu'il est « dans la salle froide A ». C'est le fichier `pollers.toml` de la passerelle qui associe adresse d'esclave, identifiant (`env-01`), zone métier et numéro de série attendu.

Si le numéro de série lu (registres 7–8) ne correspond pas à celui attendu pour cette adresse, le poller **ne publie pas la télémétrie** de ce nœud et lève une alarme `identity_mismatch`. Cela détecte une erreur de câblage, d'adresse ou une carte remplacée. Ce n'est **pas** de l'authentification (n'importe quel appareil sur le bus peut annoncer le même numéro), c'est un contrôle d'intégrité.

## 5. Ce qu'on attend de toi (points à décider ensemble)

1. **Accepter les registres 7–8** (numéro de série). Ils sont dans le contrat v1 mais à valider avec toi.
2. **Comment fixer l'adresse d'esclave** de chaque carte : constante à la compilation (simple, une compilation par carte) ou micro-interrupteurs/DIP (une seule image, plus pratique si on a plusieurs cartes). À toi de dire ce qui est faisable.
3. **Comment programmer le numéro de série** : constante compilée ou stockée en EEPROM. Il doit être unique par carte.
4. **Pilotage du transceiver RS485** : la gestion de la broche de direction (DE/RE) et le délai de retournement après la réponse sont à régler côté Arduino ; le montage côté Arduino n'est pas encore connu de la passerelle.
5. **Capteur de pression et PIR** : pas encore disponibles. Le contrat prévoit `0xFFFF` pour la pression absente et le FC02 optionnel, donc tu peux avancer sans.

## 6. Tester sans la passerelle

Un faux **maître**, c'est ce qu'il te faut pour tester ton esclave. Dans l'autre sens, nous avons déjà un faux esclave (`sim/modbus/`) qui sert à tester la passerelle. Pour toi, le moyen le plus simple est d'utiliser n'importe quel client Modbus RTU (par exemple `pymodbus`, ou un utilitaire comme `mbpoll`) branché sur l'adaptateur USB-RS485, en lisant les registres d'entrée 0 à 8 de l'esclave 1 : la requête brute est `01 04 00 00 00 09 30 0C`.

Critère « terminé » côté Arduino : une lecture des 9 registres renvoie des valeurs cohérentes avec les unités et les sentinelles du tableau ci-dessus, et les écritures sur les registres de maintien changent bien le comportement de `temp_alarm`.

## 7. Sécurité (pourquoi ce n'est pas un détail)

Modbus n'a ni authentification ni chiffrement : n'importe quel équipement sur le bus peut lire les registres et **écrire les seuils**. C'est volontaire dans la version vulnérable du projet, car c'est la cible des scénarios d'attaque de l'équipe Red Team ; la version durcie ne change pas ce contrat, elle isole le bus. Le poller détecte une modification des réglages (`config_drift`) mais ne l'empêche pas. Il ne faut donc pas supposer que la valeur d'un seuil ou d'une période est fiable côté Arduino sans la valider.
