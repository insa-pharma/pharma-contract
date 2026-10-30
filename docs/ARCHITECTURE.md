# Architecture technique — Surveillance et traçabilité de produits pharmaceutiques

Version 0.1, brouillon de travail (octobre 2026). INSA CVL, STI 5A, option 2SEC. Encadrant : E. Ferrère.

Ce document consigne **ce qui est décidé, ce qui est proposé et ce qui reste ouvert**, avec les raisons. Il se met à jour à chaque décision. Spécification d'interface : [`contrat/CONTRAT.md`](../contrat/CONTRAT.md).

Statuts : **décidé** (arrêté par le propriétaire du composant concerné, relu par les autres via la pull request), **proposé** (à valider), **ouvert** (non tranché).

---

## 1. Objectifs et périmètre

### Ce que le sujet demande (diapositives 3 et 4 du PDF de projets)

Surveiller les conditions de stockage et de transport de produits pharmaceutiques (température, humidité, pression), sécuriser physiquement les entrepôts (accès, intrusion, vidéo consultable à distance), assurer la traçabilité, et livrer **deux versions de l'infrastructure (vulnérable et durcie)** avec pare-feu, IDS, SIEM et tests d'attaque/défense Red/Blue Team.

### Exigences supplémentaires de l'encadrant (verbal, rapportées par l'équipe)

Un système multi-protocoles évolutif (remplacement futur de l'Arduino par une carte PSoC), une version sécurisée, de la traçabilité, et surtout la partie sécurité (SIEM, détection d'anomalies, simulation d'attaques), qui est la base de la seconde partie du projet.

### Périmètre par niveaux

| Niveau | Contenu | Nature |
|---|---|---|
| 1. Socle | Modbus RTU (température, humidité, pression), camion en LoRaWAN avec enregistrement différé, bus et ThingsBoard avec alarmes 2–8 °C, pare-feu RPi3, caméra, contrôle d'accès, détection d'intrusion, **version vulnérable de bout en bout** | indispensable |
| 2. Sécurité | Version durcie, SIEM, IDS, détection d'anomalies, scénarios d'attaque, Red/Blue Team | cœur de la 2ᵉ partie |
| 3. Extensions | Modbus TCP puis OPC UA, nœud PSoC, OTAA avec un vrai concentrateur, lots et expéditions, application mobile | selon le temps |

### Livrable et calendrier

Démo, rapport, soutenance. Fin du projet mi-janvier, fin de semestre le vendredi 5 février. Jalon visé : version vulnérable de bout en bout **avant décembre**, pour laisser décembre à la sécurité.

### Scénario de démo (environ 12 minutes, chaque ligne devient un test automatique en profil `sim`)

1. Vue d'ensemble ThingsBoard, deux entrepôts (`wh01` réel, `wh02` simulé).
2. Température, humidité et pression en direct (Modbus RTU).
3. Valeur hors 2–8 °C : alarme et notification.
4. Le camion revient et décharge ; trajet GPS et courbe de température.
5. Badge valide, badge inconnu : événements d'accès.
6. Mouvement hors horaires : alarme et enregistrement vidéo.
7. Un agent consulte la vidéo à distance, de façon authentifiée.
8. Traçabilité : qui est entré, quand, et la température du camion pendant son trajet.
9. Trois attaques sur la version vulnérable (faux message MQTT, rejeu LoRaWAN, clonage de badge ou écriture Modbus).
10. Mêmes attaques sur la version durcie : bloquées, avec alertes pare-feu, IDS et SIEM.
11. Bonus : Modbus TCP vulnérable puis OPC UA sécurisé.

### Couverture des exigences du sujet

Chaque exigence du sujet est reliée à une étape de la démo (C1 à C12, O1 à O7). Les éléments non montrables en direct vont dans le rapport : le PSoC (le contrat Modbus le rend interchangeable) et l'architecture extensible par adaptateurs. Exigences manquantes avant révision : détecteurs de mouvement, plusieurs entrepôts, intrusion, vidéo à distance, traçabilité, pare-feu et IDS visibles. Elles sont toutes intégrées au scénario ci-dessus.

---

## 2. Architecture cible

```
 CLOUD / machine de l'école
 ┌───────────────────────────────────────────┐
 │ ThingsBoard CE    Wazuh manager            │
 └──────────────────▲────────────────────────┘
                    │ tailnet (Tailscale), connexions sortantes
 ENTREPÔT wh01      │
 ┌──────────────────┴───────────────────────────────────────────┐
 │ RPi3 : routeur · point d'accès WiFi · pare-feu nftables       │
 └──────┬─────────────────────────────────────┬──────────────────┘
        │ Ethernet (LAN)                      │ WiFi (sous-réseau IoT)
 ┌──────┴────────────── RPi5 ───────────────┐ └─ ESP32-CAM  ◄─ le RPi5 tire le flux
 │ Mosquitto (bus interne)                  │
 │ modbus-poller · lora-ingest · access      │
 │ recorder · tb-bridge · ChirpStack         │
 │ Suricata · agent Wazuh · chrony           │
 └──┬──────────────┬───────────────┬────────┘
    │ USB-RS485    │ SPI + UART    │ USB
    │ Modbus RTU   │ HAT Dragino   │ lecteur de cartes ◄─ carte JavaCard
 Arduino+BME280    │ (LoRa + GPS)
 (+PIR)            ┊ radio LoRaWAN 868 MHz, ABP, un seul canal
 MOBILITÉ          ┊
 ┌─────────────────┴────┐
 │ ESP32 LoRa-GPS camion │  enregistre hors de portée, décharge au retour
 └───────────────────────┘
```

### Composants et propriétaires

| Composant | Interface | Propriétaire |
|---|---|---|
| Nœud capteurs (Arduino, puis PSoC) | table de registres Modbus RTU | Arduino |
| Nœud camion | trame LoRaWAN (port 10 et 11) | mobilité ×2 |
| Caméra ESP32-CAM | HTTP `/capture`, `/stream` | mobilité n°2 |
| Lecteur et carte | APDU ISO 7816 | JavaCard |
| Passerelle d'entrepôt (RPi5) | adaptateurs, bus, pont ThingsBoard | RPi5 |
| Périmètre réseau (RPi3) | pare-feu, accès | WAN |
| Plateforme cloud | ThingsBoard | serveur |
| SIEM, IDS, anomalies (Blue) | alertes, règles | WAN + serveur (proposé) |
| Attaques (Red) | scénarios et preuves | Arduino + JavaCard (proposé) |
| Simulation, tests, CI | `pharma-contract` | à désigner |

### Principes

1. **Contrat d'abord.** On développe contre `CONTRAT.md` et un mock, jamais contre le matériel d'un coéquipier.
2. **Adaptateurs.** Chaque protocole est un adaptateur qui traduit vers l'enveloppe commune. Ajouter un protocole = écrire un adaptateur et sa fiche dans le contrat, sans changer le reste. Une seule abstraction, pas de framework.
3. **Simulation d'abord.** Chaque étape marche en profil `sim` avant le profil `hw`.
4. **Local d'abord.** L'entrepôt fonctionne sans internet : décision d'accès locale, file persistante vers ThingsBoard.
5. **Deux versions, un contrat.** Vulnérable et durcie partagent les mêmes interfaces. Seule la configuration de sécurité change.
6. **Aucun secret dans un dépôt.** Clés LoRaWAN, jetons ThingsBoard, mots de passe WiFi, clés Tailscale vont dans des fichiers `.env` non versionnés.
7. **Une direction de dépendance.** Tous les dépôts dépendent du contrat (version étiquetée), jamais les uns des autres. La seule frontière entre composants est le contrat plus une image de conteneur.
8. **Types générés depuis les schémas.** Le contrat publie des schémas JSON et des vecteurs de test, pas de bibliothèque dans un langage donné. Chaque dépôt génère ses propres types : un changement du contrat fait échouer la compilation au lieu de dériver en silence.

### Dépôts et langages (organisation GitHub `insa-pharma`, dépôts privés)

| Dépôt | Contenu | Langage | Propriétaire |
|---|---|---|---|
| `pharma-contract` | spec, schémas JSON, vecteurs de test, mocks, tests de contrat, intégration (`compose`), ce document | Python typé (D26) | à désigner |
| `pharma-gateway` | services du RPi5 : poller Modbus, ingestion LoRaWAN, enregistreur vidéo, pont ThingsBoard | **Rust** (voir D17) | RPi5 |
| `pharma-firmware-warehouse` | nœud capteurs (Arduino, puis PSoC) et ESP32-CAM | C/C++ (Arduino / PlatformIO) | Arduino, mobilité n°2 |
| `pharma-firmware-mobility` | ESP32 du camion, avec la bibliothèque d'encodage de trame | C++ (PlatformIO) | mobilité ×2 |
| `pharma-javacard` | applet, client APDU de référence, service `access` (livré en image de conteneur) | Java, Rust ou autre : voir O14 | JavaCard |
| `pharma-infra` | réseau RPi3, règles d'accès Tailscale, déploiement, configuration ThingsBoard, règles Suricata et Wazuh | Ansible, YAML | WAN, serveur |
| `pharma-security` | scénarios d'attaque (Red), règles de détection (Blue), preuves | scripts | Arduino, JavaCard (Red) ; WAN, serveur (Blue) |

Un dépôt `.github` public existe (D24) : GitHub exige qu'il soit public pour fournir des fichiers par défaut, donc rien de sensible dedans.

### Règles de dépendance et de version

- **Versions du contrat** : numérotation sémantique, tags `v1.x`. En v1.x on ajoute seulement des champs facultatifs ; un changement qui casse passe en v2 avec une ligne dans le `CHANGELOG`.
- **Pas de circularité** : la CI de `pharma-contract` teste le contrat et ses mocks seulement. Un flux d'intégration séparé (planifié ou manuel) assemble les images publiées des autres dépôts.
- **Chaque dépôt qui produit un service le livre en image de conteneur**, étiquetée avec une version, dans le registre de l'organisation.
- **Un `Makefile` identique** dans chaque dépôt (`make test`, `make run-sim`).

---

## 3. Journal des décisions

| # | Décision | Raison | Alternatives écartées | Statut |
|---|---|---|---|---|
| D01 | Un dépôt `pharma-contract` réunit contrat, mocks, tests et intégration. Les autres dépôts épinglent une version étiquetée | Éviter la dérive entre spec et simulation | Monorepo (refusé par l'équipe) ; contrat et intégration séparés | décidé |
| D02 | Enveloppe JSON commune et bus MQTT interne (Mosquitto sur le RPi5) | Découple les protocoles du cloud, point de capture pour l'IDS et les tests | Chaque service parle directement à ThingsBoard | proposé |
| D03 | Protocoles : **Modbus RTU et LoRaWAN obligatoires** ; Modbus TCP puis OPC UA secondaires | Cahier des charges minimal tenable ; Modbus TCP (vulnérable) puis OPC UA (sécurisé) racontent un durcissement | Tous les protocoles d'emblée (risque de ne pas finir) | décidé |
| D04 | LoRaWAN en ABP, un canal et un SF fixés, avec le HAT Dragino (SX1276) ; ChirpStack sur le RPi5 | Matériel disponible ; ce HAT n'est pas une vraie passerelle multi-canaux et n'émet probablement pas de réponse de jonction | Concentrateur SX1302/1303 (non disponible) | proposé |
| D05 | Camion : enregistrement local puis envoi différé au retour à portée | Pas de passerelle ni de 4G dans le camion ; l'historique complet suffit à la traçabilité | Passerelle embarquée avec clé 4G ; réseau public | décidé |
| D06 | ThingsBoard CE auto-hébergé sur la machine de l'école (32 Go, Debian) | Déjà en place | ThingsBoard Cloud (payant, données chez un tiers) | décidé |
| D07 | Contrôle d'accès : décision en local, journal envoyé au cloud | L'entrepôt doit s'ouvrir sans internet | Décision côté cloud | proposé |
| D08 | Alarmes de température calculées une seule fois, dans ThingsBoard (seuils 2–8 °C en attributs) | Source unique, pas de doublon | Alarmes sur la passerelle | proposé |
| D09 | Capteurs PIR et pression **simulés** tant que le matériel n'est pas obtenu ; signalé en démo et dans le rapport | Matériel à demander au retour à l'école | Attendre | décidé |
| D10 | Vidéo : le RPi5 tire le flux de la caméra ; une page de visualisation sur le RPi5, accessible seulement sur le tailnet, intégrée dans ThingsBoard. Tests automatiques vidéo : secondaires | Aucune exposition de la caméra, accès par identité ; réutilisable par une application mobile | VPN seul ; exposition publique | décidé sur le principe, à tester |
| D11 | Tailscale pour l'administration et le transport, règles d'accès versionnées, laboratoire isolé | Simplicité de déploiement | WireGuard manuel | décidé sur le principe ; variante (SaaS ou Headscale) ouverte |
| D12 | La version vulnérable ne tourne **jamais** sur l'instance partagée ou accessible hors du laboratoire | Mots de passe par défaut et services ouverts voulus ; risque réel pour le réseau de l'école | Héberger la version vulnérable sur la machine de l'école | proposé |
| D13 | Red/Blue : Blue = WAN + serveur ; Red = Arduino + JavaCard | Séparer attaque et défense | Même personne pour les deux | à discuter |
| D14 | Organisation GitHub `insa-pharma`, dépôts privés, sept dépôts (voir §2). Le firmware est en deux dépôts (entrepôt, camion) | Autonomie des membres ; le firmware de l'entrepôt et celui du camion n'ont pas de code commun | Monorepo ; un seul dépôt firmware | décidé |
| D15 | Traçabilité : définie plus tard par l'équipe. Elle repose sur l'enveloppe (heure, source, site) à laquelle on pourra ajouter un numéro de séquence ou une signature sans rien casser | Définition absente du sujet | Définir maintenant | décidé |
| D16 | PSoC : remplace l'Arduino plus tard en implémentant la même table de registres Modbus ; compatibilité du shield = problème matériel à part | Le contrat isole le reste du système | Intégrer le PSoC dès maintenant | décidé (hors périmètre immédiat) |
| D17 | **Rust** pour les services « industriels » de la passerelle (poller Modbus, ingestion LoRaWAN, adaptateurs futurs). Essai de 3 jours sur le poller, décision confirmée à la fin de la semaine 1. Critères : tranche terminée à temps, compile pour ARM 64 bits, code expliqué sans l'IA, CI en marche. Repli : Go pour le poller ; Dart envisageable pour les services de plomberie (maximum deux langages) | Langage typé sans ramasse-miettes, adapté à l'objectif embarqué et sécurité ; chaque service est un processus séparé, donc le langage peut changer sans toucher au reste | Dart (le plus maîtrisé, mais écosystème matériel mince), TypeScript, Kotlin/Java (JVM lourde sur le Pi), Go, C++ sur le chemin critique | décidé, sous réserve de l'essai |
| D18 | Les trames LoRaWAN sont **décodées dans la passerelle** (`lora-ingest`), à partir des octets déjà déchiffrés par ChirpStack. Le codec JavaScript de ChirpStack devient facultatif (affichage dans son interface), écrit en JavaScript avec `@ts-check` et JSDoc | Supprime la dépendance à JavaScript ; un seul décodeur de référence | Codec JavaScript obligatoire ; TypeScript compilé | décidé |
| D19 | La bibliothèque d'encodage de trame est écrite en C++20 sans dépendance, dans `pharma-firmware-mobility`, testable sur le Mac contre `truck_vectors.json`, avec compilation sous sanitizers et fuzzing du décodeur | Utilisable telle quelle dans le firmware ESP32 ; travaille le point faible C++ sans toucher au chemin critique | Rust `no_std` sur ESP32 (chaîne d'outils plus lourde) | proposé (propriétaire : voir O15) |
| D20 | Les trames sont vérifiées par le même fichier de vecteurs dans chaque langage : encodeur C++, décodeur Rust, codec JavaScript facultatif | Évite que trois implémentations divergent | Tests séparés par langage | proposé |
| D21 | Pas de bibliothèque partagée par langage : le contrat publie des schémas JSON, chaque dépôt génère ses types | Neutre vis-à-vis du langage ; le compilateur détecte les dérives | Paquet Python partagé | proposé |
| D22 | Les dépôts qui produisent un service le livrent en image de conteneur versionnée, y compris `access` (livré par `pharma-javacard`) | Frontière claire, déploiement homogène | Dépendance directe entre dépôts | proposé |
| D23 | Bruno (client d'API stocké en fichiers dans Git, exécutable en CI) pour tester les API REST qui existent (ThingsBoard, ChirpStack), si le besoin se confirme | Les requêtes sont versionnées avec le contrat | Collections Postman | proposé, à confirmer quand les API sont utilisées |
| D24 | Un dépôt `.github` **public** existe (créé pour une publication future). Rien de sensible dedans (IP, topologie, clés) : modèles de pull request et `SECURITY.md` seulement. Les flux de CI réutilisables restent dans `pharma-contract`, privé | GitHub exige un dépôt `.github` public pour les fichiers par défaut | Pas de `.github` | décidé |
| D25 | Pull request obligatoire, une relecture ; deux pour le contrat, dont un propriétaire concerné | Qualité sans bloquer | Poussée directe | proposé (dépend de l'offre GitHub, O8) |
| D26 | **Python** pour l'outillage de test, les simulateurs et les scripts d'attaque de `pharma-contract`, jamais en production sur la passerelle. Types annotés, `pyright` ou `mypy` en mode strict, `ruff`, `pytest`, `pyproject.toml` par dépôt | Standard de l'automatisation en embarqué et en sécurité ; le code existant (mock caméra, tests de schémas) fonctionne ; toute l'équipe peut le maintenir | TypeScript (profil web), Rust (coût sans gain pour de l'outillage) | décidé |
| D27 | **Rust aussi pour `tb-bridge` et `recorder`** : une pile cohérente sur la passerelle (Rust pour les services, Python seulement pour les tests, D26), et une faible empreinte mémoire sur un RPi5 de 4 Go. `recorder` est un superviseur léger du processus `ffmpeg`. Repli Go pour un service seulement si l'essai Rust échoue (maximum deux langages) | Un binaire statique par service, pas de machine virtuelle ni de ramasse-miettes : quelques Mo par service attendus (à mesurer à l'étape 1). Go aurait convenu aussi, mais ajouterait un second langage de production | Go pour la plomberie, Dart | décidé, sous réserve de l'essai (D17) |
| D28 | **Le poller écrit les registres de configuration au démarrage**, à partir d'un fichier de configuration, puis relit les registres de maintien à chaque cycle et signale tout écart (`config_drift`) dans `status`. Cela remplace la règle « le poller ne fait que lire » | La configuration devient reproductible (fichier versionné) ; la relecture donne gratuitement une détection d'écriture Modbus non autorisée, qui alimente le scénario d'attaque n°4 de l'étape 7 et la partie Blue | Outil d'administration séparé ; registres jamais écrits (configuration à la main sur l'Arduino) | décidé |
| D29 | **Plusieurs nœuds Modbus sur un même bus RS485** (par exemple une salle par Arduino). Chaque nœud a son adresse d'esclave (1 à 247) et son `src.id` (`env-01`, `env-02`…). Le poller les interroge **l'un après l'autre** (un seul maître, un seul échange à la fois). Fichier de configuration `pollers.toml` : liste de nœuds avec adresse, `src.id`, zone, période, seuils | Modbus RTU est multi-nœuds par conception (bus RS485). Coût d'un échange de 9 registres à 9600 bauds : environ 31 octets (requête 8 + réponse 23) × 11 bits ÷ 9600 ≈ 36 ms plus les silences, soit de l'ordre de 50 ms par nœud : 10 nœuds tiennent largement dans 10 s. Le nom de la zone reste de la métadonnée (configuration, attribut ThingsBoard), le contrat de l'enveloppe ne change pas (voir O18) | Un bus par Arduino (un adaptateur USB-RS485 chacun) | décidé |
| D30 | **Source unique des seuils : `pollers.toml`**, nœud par nœud. Le poller écrit les seuils dans les registres de maintien (alarme **locale** de l'Arduino, bit `temp_alarm`), et un script de `pharma-infra` pose les attributs `temp_min_c`/`temp_max_c` de ThingsBoard (alarme **officielle**, calculée une seule fois dans ThingsBoard) depuis le même fichier. Valeurs par défaut 2,0 et 8,0 °C (contrat §3), vérifiées par un test de `pharma-contract` | Deux jeux de seuils divergent sinon en silence | Saisie manuelle dans ThingsBoard | décidé (la pose des attributs par l'API REST de ThingsBoard reste à vérifier) |
| D31 | **Identité et emplacement séparés.** L'Arduino ne porte qu'un identifiant technique (adresse d'esclave Modbus, éventuellement un numéro de série, O20). `pollers.toml` fait la « traduction métier » : adresse → `src.id` stable (`env-01`) + `zone` (emplacement, par exemple `salle-froide-a`). La zone est publiée dans le message `status` du nœud (champ facultatif, schéma mis à jour) et devient un attribut ThingsBoard. Elle n'apparaît jamais dans la télémétrie | Déplacer un capteur ne change ni son identifiant ni son historique ; le contrat de télémétrie ne change pas ; le bus ne transporte aucun nom métier | Zone codée dans `src.id` (`env-salle-froide-a`) | décidé |
| D32 | **Numéro de série dans les registres d'entrée 7–8** (uint32, unique par carte, `0` = non programmé), ajout compatible v1.x. Le poller lit désormais les registres 0 à 8 et, si `pollers.toml` indique un numéro attendu, compare : écart ou `0` → pas de télémétrie pour ce nœud, alarme `identity_mismatch` (critique), champ `serial` dans le `status` | Détecte une carte échangée, une mauvaise adresse ou un appareil de remplacement ; matière pour la partie Blue. **Limite assumée :** ce n'est pas une authentification, un attaquant peut annoncer le même numéro | Adresse d'esclave seule | décidé (à faire accepter par la personne Arduino) |
| D33 | **Format de configuration du poller : `pollers.toml`** (TOML, version `schema = 1`). Un seul `[bus]` par poller (une deuxième instance si un deuxième adaptateur apparaît), `[defaults]` hérités par chaque `[[node]]`, `serial` facultatif (absent = pas de vérification d'identité, avertissement dans le journal), `config_drift` toujours actif, pas de rechargement à chaud, aucun secret dans le fichier. Le **schéma JSON** (`contrat/schemas/pollers.schema.json`) couvre types, plages et motifs ; les règles de cohérence (unicité de `id`, `slave`, `serial`, `pir` ; `temp_min_c` < `temp_max_c` effectifs) sont dans `test_pollers.py`, que le poller Rust doit reproduire sur les mêmes cas invalides | TOML : commentaires, types explicites (entier ≠ flottant ≠ texte, pas d'ambiguïté `no`/`off`), grammaire courte, outillage natif en Rust (`serde` + crate `toml`) ; la configuration est peu imbriquée, donc `[[node]]` suffit. Le fichier est lu par deux consommateurs (poller, script de `pharma-infra`) : c'est une interface, donc un schéma | YAML (commentaires, mais typage implicite piégeux et plusieurs versions de la spécification ; le crate `serde_yaml` a, à ma connaissance, été archivé par son auteur), JSON (pas de commentaires, verbeux pour de la configuration écrite à la main) | décidé |
| D34 | **Trois classes de fichiers.** (1) *Liés au programme*, versionnés dans le dépôt du programme : schéma, fichier exemple, valeurs par défaut, `.env.example`. (2) *Configuration de site*, sans secret, propre à un déploiement : `pollers.toml` réel, `compose` de déploiement (versions d'images figées). Le `compose` de développement et de simulation (`sim`, `hw`) reste dans `pharma-gateway`, avec les programmes. (3) *Secrets et fichiers d'exécution*, **jamais dans un dépôt** : mots de passe MQTT, jeton ThingsBoard, clés LoRaWAN, clé d'authentification Tailscale, certificats, `.env` ; ils sont créés sur la machine (ou via un coffre) et seul le `.env.example` est versionné. La classe (2) est versionnée dans `pharma-infra` et déployée vers `/etc/pharma/` | Principe 6 de ce document, étendu : un secret ne se relit pas dans l'historique Git ; une configuration sans secret gagne à être relue et restaurable (les seuils sont un choix métier qui se révise) | Tout hors dépôt (perd la relecture et le retour arrière, et le script ThingsBoard n'aurait plus de source) décidé. Règle pour `pollers.toml` : `pollers.example.toml` dans `pharma-gateway` ; en développement, une copie locale `pollers.toml` ignorée par Git ; le fichier réel d'un site dans `pharma-infra` quand on déploie vraiment. Ansible n'est pas requis avant l'étape 6 |

---

## 4. Points ouverts

| # | Question | Pour qui | Dépend de |
|---|---|---|---|
| O1 | Le HAT Dragino fonctionne-t-il sur Pi 5 ? Test d'un registre du SX1276 sur la journée | RPi5 | étape 0 du plan |
| O2 | Tailscale SaaS ou Headscale sur la machine de l'école ? | équipe | voir §5 |
| O3 | Combien d'utilisateurs ont besoin du tailnet ? L'offre gratuite affichait jusqu'à 6 utilisateurs et un usage non commercial (à revérifier) | équipe | O2 |
| O4 | HTTPS pour la page de visualisation vidéo : certificats via Tailscale ou via un proxy local ? | RPi5 | O2 |
| O5 | Autorisation écrite de M. Ferrère pour les tests d'attaque (périmètre, machines concernées) | équipe | avant toute attaque |
| O6 | Quels protocoles sont obligatoires pour la recette ? Traçabilité attendue ? | équipe | e-mail à M. Ferrère |
| O7 | RAM du RPi5 : **4 Go confirmés**. Budget à mesurer à l'étape 1 avec ChirpStack, PostgreSQL, Redis, Mosquitto, Suricata, Wazuh agent, `ffmpeg` et les 5 services Rust. Suricata et PostgreSQL sont les postes à surveiller | RPi5 | étape 1 |
| O8 | Plateforme d'intégration continue : GitHub Actions sur dépôts privés. Minutes incluses et règles de protection de branche selon l'offre de l'organisation | équipe | offre GitHub |
| O9 | Algorithme de signature de la carte (ECDSA P-256 ou AES-CMAC) | JavaCard | cours de cartes à puce |
| O10 | Où placer le PIR : sur l'Arduino (entrée discrète Modbus) ou sur la caméra ? | Arduino + caméra | matériel |
| O11 | Détection d'anomalies : règles côté ThingsBoard et Wazuh d'abord ? | Blue | — |
| O12 | Un compte et un tailnet dédiés au projet, avec deux administrateurs, plutôt que le compte personnel d'une personne | équipe | O2 |
| O13 | ~~Langage de l'outillage de test et des mocks~~ → **résolu : Python (D26)** | — | — |
| O14 | Langage du service `access` et du client APDU (dépend de la bibliothèque PC/SC disponible dans chaque langage) | JavaCard | O13 |
| O15 | Qui écrit la bibliothèque C++ de trame : la passerelle (RPi5) ou la personne mobilité ? | RPi5, mobilité | — |
| O16 | L'accès aux flux de CI réutilisables entre dépôts privés de l'organisation doit être autorisé dans les paramètres GitHub Actions (à vérifier) | équipe | O8 |
| O17 | Bruno gère-t-il les protocoles dont nous avons besoin ? À ma connaissance il couvre HTTP, GraphQL et gRPC, et je n'ai rien trouvé sur MQTT : il ne remplace donc pas les tests MQTT/Modbus/LoRaWAN | `pharma-contract` | D23 |
| O18 | ~~Où vit le nom de zone~~ → **résolu : `pollers.toml` + champ `zone` du `status` (D31)** | — | — |
| O19 | ~~Source des seuils~~ → **résolu : `pollers.toml` (D30)**. Reste à vérifier que l'API REST de ThingsBoard pose les attributs côté serveur | serveur | D30 |
| O20 | ~~Numéro de série lisible~~ → **résolu : registres 7–8 (D32)**. Reste : format de `pollers.toml`, et accord de la personne Arduino | RPi5, Arduino | D32 |

## 5. Risques

1. **Calendrier court** : environ 8 à 9 semaines utiles. Atténuation : niveau 1 étroit, extensions jamais bloquantes.
2. **Radio sur Pi 5 non confirmée** (O1). Atténuation : test le premier jour, repli en simulation et demande d'une passerelle à l'école.
3. **Matériel tardif** (caméras, PIR, pression). Atténuation : mocks fidèles au contrat, test de conformité rejouable sur le vrai matériel.
4. **Surface d'attaque réelle** : une version vulnérable accessible depuis internet ou le réseau de l'école (D12, O5).
5. **Dépendance à un service tiers** (Tailscale). À discuter dans le rapport avec l'alternative auto-hébergée.
6. **Contrat qui dérive** sans tests automatiques. Atténuation : CI qui teste chaque mock contre le contrat.
7. **Courbe d'apprentissage de Rust sur le chemin critique.** La passerelle est le point où tout converge. Atténuation : essai de 3 jours avec critères d'arrêt, services séparés par le bus donc remplaçables un par un, repli Go.
8. **Mémoire du RPi5 (4 Go).** Beaucoup de services sur une seule carte (voir O7). Atténuation : mesure dès l'étape 1, limites mémoire par conteneur, règles Suricata réduites, et en dernier recours déplacer Wazuh ou la vidéo ailleurs.
