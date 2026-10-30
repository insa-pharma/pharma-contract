# pharma-contract

Contrat d'interface, schémas, vecteurs de test et simulateurs du projet « Surveillance et traçabilité de produits pharmaceutiques » (INSA CVL, STI 5A, option 2SEC).

Chaque composant se développe **contre ce contrat et un simulateur**, sans attendre le matériel des autres. Un composant est terminé quand il passe les tests de contrat, qu'il soit réel ou simulé.

**Statut : v1.0-rc1 (candidate).** Chaque propriétaire relit sa section ; l'étiquette `v1.0` sera posée une fois les remarques traitées. État détaillé et reste à faire : [`docs/ETAT_AVANCEMENT.md`](docs/ETAT_AVANCEMENT.md).

## Contenu

| Chemin | Contenu |
|---|---|
| [`contrat/CONTRAT.md`](contrat/CONTRAT.md) | le contrat v1 : Modbus RTU, enveloppe MQTT, ThingsBoard, trame LoRaWAN du camion, APDU JavaCard, vidéo |
| [`contrat/schemas/`](contrat/schemas) | schémas JSON (enveloppe, configuration du poller) et leurs tests |
| [`contrat/vectors/`](contrat/vectors) | cas de test partagés entre langages (configuration du poller : 2 valides, 15 invalides) |
| [`contrat/lorawan/`](contrat/lorawan) | codec de référence de la trame camion, vecteurs d'octets, codec JavaScript facultatif |
| [`contrat/examples/`](contrat/examples) | exemple de configuration du poller (`pollers.example.toml`) |
| [`sim/modbus/`](sim/modbus) | faux nœuds Modbus RTU sur port série virtuel, pannes à la demande |
| [`sim/cam/`](sim/cam) | mock ESP32-CAM et test de conformité |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | architecture, journal des décisions, points ouverts, risques |
| [`docs/RESUME_ARDUINO_GATEWAY.md`](docs/RESUME_ARDUINO_GATEWAY.md) | résumé de l'interface Arduino ↔ passerelle |

## Lancer les tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python3 contrat/schemas/test_schemas.py
python3 contrat/schemas/test_pollers.py
python3 contrat/lorawan/truck_frame.py      # régénère truck_vectors.json
node contrat/lorawan/test_codec.js          # Node.js requis
python3 sim/modbus/test_sim_modbus.py
```

Le test de la caméra demande de lancer le mock avant (voir [`sim/cam/README.md`](sim/cam/README.md)).

## Règle de changement

On ne modifie `contrat/CONTRAT.md` que par pull request relue par les propriétaires des composants concernés. Un changement incompatible incrémente la version (`v: 2`). Pas d'intégration continue pour l'instant (voir l'état d'avancement).
