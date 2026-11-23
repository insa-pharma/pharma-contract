"""Test de conformité du contrat vidéo (CONTRAT.md §6).

Le MÊME test passe contre le mock et contre la vraie ESP32-CAM : c'est ce qui prouve que
le mock est fidèle, et que le vrai firmware respecte le contrat.

  python3 test_cam_contract.py --main http://127.0.0.1:8080 --stream http://127.0.0.1:8081
  python3 test_cam_contract.py --main http://cam-01.lan --stream http://cam-01.lan:81
  python3 test_cam_contract.py ... --faults      # mock seulement : injecte des pannes

Stdlib uniquement.
"""
import argparse
import http.client
import re
import sys
import time
from urllib.parse import urlparse


def conn(base, timeout=5):
    u = urlparse(base)
    return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)


def is_jpeg(b):
    return b[:2] == b"\xff\xd8" and b[-2:] == b"\xff\xd9"


def read_parts(base, seconds):
    """Lit le flux pendant `seconds` ; retourne (status, content_type, [(x_timestamp, jpeg_bytes)])."""
    c = conn(base)
    c.request("GET", "/stream")
    r = c.getresponse()
    if r.status != 200:
        r.read()
        c.close()
        return r.status, None, []
    ctype = r.getheader("Content-Type", "")
    boundary = re.search(r"boundary=(.+)$", ctype).group(1).encode()
    buf, parts, end = b"", [], time.time() + seconds
    try:
        while time.time() < end:
            chunk = r.read1(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                m = re.search(rb"--" + re.escape(boundary) + rb"\r\n(.*?)\r\n\r\n", buf, re.S)
                if not m:
                    break
                hdr = m.group(1).decode()
                clen = int(re.search(r"Content-Length: (\d+)", hdr).group(1))
                start = m.end()
                if len(buf) < start + clen:
                    break
                ts = re.search(r"X-Timestamp: ([\d.]+)", hdr)
                parts.append((float(ts.group(1)) if ts else None, buf[start:start + clen]))
                buf = buf[start + clen:]
    except (TimeoutError, OSError):
        pass
    finally:
        c.close()
        time.sleep(0.3)  # laisse au serveur le temps de libérer le créneau de flux (un seul client)
    return r.status, ctype, parts


def wait_idle(main_base, timeout=3):
    """Mock seulement : attend que le serveur ait libéré le créneau de flux."""
    end = time.time() + timeout
    while time.time() < end:
        c = conn(main_base)
        c.request("GET", "/__state")
        body = c.getresponse().read().decode()
        c.close()
        if '"clients": 0' in body:
            return
        time.sleep(0.1)


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        check.failed += 1


check.failed = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    ap.add_argument("--stream", required=True)
    ap.add_argument("--faults", action="store_true", help="pannes injectables (mock uniquement)")
    ap.add_argument("--min-fps", type=float, default=3.0)
    a = ap.parse_args()

    print("/capture")
    c = conn(a.main)
    c.request("GET", "/capture")
    r = c.getresponse()
    body = r.read()
    check(r.status == 200, "200")
    check(r.getheader("Content-Type") == "image/jpeg", "Content-Type image/jpeg")
    check(is_jpeg(body), f"JPEG valide ({len(body)} octets)")

    print("/stream (4 s)")
    status, ctype, parts = read_parts(a.stream, 4)
    check(status == 200, "200")
    check(ctype.startswith("multipart/x-mixed-replace"), f"multipart/x-mixed-replace ({ctype})")
    check(len(parts) > 0 and all(is_jpeg(p[1]) for p in parts), f"{len(parts)} images, toutes JPEG valides")
    fps = len(parts) / 4
    check(fps >= a.min_fps, f"débit {fps:.1f} i/s >= {a.min_fps}")
    ts = [p[0] for p in parts if p[0] is not None]
    check(len(ts) == len(parts) and ts == sorted(ts), "X-Timestamp présent et croissant")

    if a.faults:
        print("pannes injectées (mock)")
        def set_fault(mode):
            c = conn(a.main)
            c.request("GET", f"/__fault?mode={mode}")
            c.getresponse().read()
            c.close()

        def rp(seconds):
            res = read_parts(a.stream, seconds)
            wait_idle(a.main)
            return res

        # drop : un flux en cours est coupé, puis une reconnexion fonctionne
        import threading
        res = {}
        t = threading.Thread(target=lambda: res.update(r=read_parts(a.stream, 6)))
        t.start()
        time.sleep(1.5)
        t_drop = time.time()
        set_fault("drop")
        t.join()
        check(time.time() - t_drop < 4, "drop : le flux est coupé en moins de 4 s")
        status, _, parts = rp(2)
        check(status == 200 and len(parts) > 0, "drop : reconnexion immédiate possible")

        # stall : connexion ouverte mais plus d'images
        set_fault("stall")
        status, _, parts = rp(2)
        check(status == 200 and len(parts) == 0, "stall : connexion ouverte, aucune image")

        # down : 503 partout
        set_fault("down")
        c = conn(a.main)
        c.request("GET", "/capture")
        check(c.getresponse().status == 503, "down : /capture répond 503")
        status, _, _ = rp(1)
        check(status == 503, "down : /stream répond 503")

        set_fault("none")
        status, _, parts = rp(2)
        check(status == 200 and len(parts) > 0, "retour à la normale")

        # un second client simultané est refusé (prudence ESP32)
        results = {}
        t1 = threading.Thread(target=lambda: results.update(a=read_parts(a.stream, 3)))
        t1.start()
        time.sleep(1)
        s2, _, _ = read_parts(a.stream, 1)
        t1.join()
        check(s2 == 503 and results["a"][0] == 200, "second flux simultané : 503, le premier continue")

    print("\n" + ("ÉCHEC: %d vérification(s)" % check.failed if check.failed else "TOUT PASSE"))
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
