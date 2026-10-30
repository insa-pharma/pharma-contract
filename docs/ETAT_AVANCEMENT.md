# État d'avancement — contrats d'interface, tests et simulation

Point au 30 octobre 2026, côté passerelle RPi5 et contrat. Pour savoir **où on en est** et **ce qu'il reste à faire** sans lire tout le journal de décisions.

## En bref

- **Le contrat v1 est rédigé en entier** (Modbus, enveloppe MQTT, ThingsBoard, trame LoRaWAN du camion, APDU JavaCard, vidéo), avec schémas JSON, vecteurs de test et simulateurs pour trois d'entre eux.
- **Rien n'est encore publié** : les sept dépôts de l'organisation existent mais sont vides (aucun commit). Tout vit pour l'instant dans un dossier de travail.
- **Aucun propriétaire de composant n'a encore relu le contrat.** C'est le vrai point bloquant pour le figer : un contrat figé sans l'accord de ceux qui le respectent ne sert à rien.
- Six suites de tests passent aujourd'hui, en local. Il n'y a pas encore d'intégration continue.

## Ce qui existe, par contrat

| Contrat | Spécification | Tests automatiques | Simulation | À valider avant gel |
|---|---|---|---|---|
| §1 Modbus RTU (Arduino ↔ RPi5) | rédigée, multi-nœuds, numéro de série (registres 7–8) | schéma de configuration du poller : 17 cas (2 valides, 15 invalides) | faux nœuds Modbus sur port série virtuel, pannes à la demande | accord de la personne Arduino ; timings sur le vrai bus |
| §2 Enveloppe et topics MQTT | rédigée | 9 exemples valides et 9 invalides contre le schéma JSON | — | relecture serveur / sécurité |
| §3 RPi5 → ThingsBoard | rédigée | rien | rien | format exact de l'API *Gateway* de la version installée ; pose des attributs par l'API REST |
| §4 Trame LoRaWAN du camion | octets figés (port 10 lot, port 11 heartbeat) | codec Python et JavaScript identiques sur les mêmes vecteurs (23 mesures) | pas encore de simulateur de trajet | accord des deux personnes mobilité ; paramètres radio dépendants du test du HAT |
| §5 APDU JavaCard ↔ lecteur | rédigée | rien | rien | choix de l'algorithme de signature ; relecture JavaCard |
| §6 Vidéo ESP32-CAM | rédigée (valeurs du firmware d'exemple d'Espressif) | test de conformité, avec pannes | mock de la caméra | à reconfirmer si un autre firmware est utilisé |

## Ce qu'on peut figer maintenant, et ce qui reste provisoire

- **Figeable tel quel :** conventions globales (§0), enveloppe et topics (§2), les **octets** de la trame camion (§4.2 à §4.4), les APDU (§5, l'algorithme de signature ne change pas l'interface), la table de registres Modbus (§1) *sous réserve de l'accord Arduino*.
- **À marquer provisoire dans le texte :** l'API *Gateway* de ThingsBoard (§3), les paramètres radio (§4.1, tant que le test du HAT sur Pi 5 n'est pas fait), les temps de réponse sur le vrai bus RS485.

## Reste à faire

### Spécification
1. Obtenir l'accord de la personne Arduino sur les registres 7–8 (numéro de série), sur la façon de fixer l'adresse d'esclave et sur le comportement en cas d'écriture invalide (exception Modbus 03, aujourd'hui seulement dans le simulateur).
2. Faire relire §4 par les deux personnes mobilité et §5 par la personne JavaCard (trancher l'algorithme de signature).
3. Vérifier dans la documentation de la version installée : API *Gateway* de ThingsBoard, champs des événements d'uplink de ChirpStack.
4. Définir la traçabilité (D15) et obtenir l'autorisation écrite pour les tests d'attaque (mail de cadrage à M. Ferrère, pas encore envoyé).
5. Nommer un propriétaire par composant dans la table du §7 (aujourd'hui des rôles, pas des personnes), y compris pour la bibliothèque C++ de trame.

### Tests automatiques
1. **Intégration continue** : aucune n'existe. À écrire : exécution des six suites, formatage et analyse statique (`ruff`, `pyright`), un seul point d'entrée (`make test`).
2. Dépendances de l'outillage Python à déclarer proprement (`pyproject.toml`) : `jsonschema`, `pyserial`, `pillow`, et `pymodbus` en option.
3. Test de contrat **sur le bus MQTT** : capturer les messages réellement publiés et les valider contre le schéma (prévu avec le poller).
4. Tests de la charge utile vers ThingsBoard (§3) et de la décision d'accès (§5, les 7 cas de `reason`) : rien n'existe.
5. Les implémentations (poller Rust, encodeur C++ du camion) rejouent **les mêmes vecteurs** que Python : à brancher quand elles existent.

### Simulation
1. Simulateur de trajet du camion (rejoue un parcours GPS en trames conformes à `truck_vectors.json`).
2. Simulateur de lecteur et de cartes (JavaCard) : jCardSim ou lecteur virtuel, à choisir.
3. Injection d'uplinks dans ChirpStack, instance ThingsBoard locale.
4. Un `docker compose --profile sim` qui lance toute la chaîne sans matériel : à écrire.
5. Limites connues du faux bus Modbus : il tolère 20 ms de silence entre octets (la norme impose environ 4 ms à 9600 bauds), sans bruit ni collision. Les temps réels sont à mesurer sur le matériel.

### Côté passerelle (pour information)
Essai Rust du poller (3 jours), test radio du HAT Dragino sur Pi 5 (bloqué par la rehausse mécanique), puis les étapes du plan : socle, Modbus, pont ThingsBoard, LoRaWAN, accès et vidéo, durcissement.

## Ce qu'on attend de chacun

| Qui | Action |
|---|---|
| Arduino | lire [le résumé Arduino ↔ passerelle](RESUME_ARDUINO_GATEWAY.md), répondre aux 4 points du §5 |
| Mobilité (×2) | relire §4 : en-têtes, enregistrements, règles d'envoi, compteur de trames |
| JavaCard | relire §5, trancher l'algorithme de signature |
| Serveur (ThingsBoard) | relire §2 et §3, dire si la règle d'alarme sur attributs `temp_min_c` / `temp_max_c` convient |
| WAN | dire ce qui est autorisé sur le réseau de l'école (VPN, ports) |
| Blue / SIEM | relire §2 : quels champs il vous faut pour détecter (`config_drift`, `identity_mismatch`) |

## Comment on fige

1. Publication dans `pharma-contract` en **`v1.0-rc1`**, par pull request.
2. Chaque propriétaire relit **sa** section et approuve, ou ouvre un commentaire. Délai à fixer ensemble.
3. Une fois les remarques traitées, étiquette **`v1.0`**. Les autres dépôts épinglent cette version.
4. Ensuite, tout changement passe par pull request relue par les propriétaires concernés ; un changement incompatible incrémente la version de l'enveloppe (`v: 2`).
