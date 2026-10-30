# Mock ESP32-CAM

Remplace `cam-01` tant que la carte n'est pas arrivée, et sert de test de non-régression ensuite.

```bash
pip install pillow
python3 esp32cam_mock.py --port 8080            # /capture sur 8080, /stream sur 8081
python3 test_cam_contract.py --main http://127.0.0.1:8080 --stream http://127.0.0.1:8081 --faults
```

Sans `--faults`, le même test s'exécute contre la vraie carte :
`python3 test_cam_contract.py --main http://cam-01.lan --stream http://cam-01.lan:81`

## Pannes injectables (mock seulement)

`GET /__fault?mode=` : `drop` (coupe les flux en cours), `stall` (flux ouvert mais figé), `down` (503 partout), `none`. `GET /__state` donne le mode et le nombre de clients.

## Enregistrement par segments (ce que fera `recorder`)

Commande validée contre le mock (segments de 3 s, 30 images chacun à 10 i/s) :

```bash
ffmpeg -use_wallclock_as_timestamps 1 -i http://127.0.0.1:8081/stream \
  -c copy -f segment -segment_time 300 -reset_timestamps 1 seg_%03d.mkv
```

Avec `-c copy`, aucun ré-encodage : le MJPEG est écrit tel quel dans les `.mkv`.

## Ce que le mock ne fait pas

- Pas d'émulation du firmware ni du capteur : il reproduit le contrat HTTP, pas la carte.
- Le nombre de flux simultanés est réglé à 1 par prudence (`--max-stream-clients`) ; le code source d'exemple ne fixe pas de limite, à mesurer sur la vraie carte.
- Le débit réel (images par seconde, taille des images, coupures WiFi) dépend de la résolution, de la qualité JPEG et de la qualité du signal : à mesurer.

Le mock met quelques secondes à démarrer à froid (import de Pillow) : attendez que les deux ports soient ouverts avant de lancer le test.
