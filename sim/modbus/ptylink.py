#!/usr/bin/env python3
"""Deux ports série virtuels reliés entre eux (modem nul), sans socat.

Ce que l'un écrit, l'autre le lit. Sert à brancher le faux esclave (sim_modbus.py) sur un port
et le poller sur l'autre, sans adaptateur USB-RS485.

    python3 ptylink.py --link-a /tmp/pharma-ttyA --link-b /tmp/pharma-ttyB

Laisser tourner. Les chemins réels (/dev/ttysNNN) sont aussi affichés.
"""
import argparse
import os
import pty
import select
import tty


def make_pty():
    master, slave = pty.openpty()
    tty.setraw(slave)
    return master, slave, os.ttyname(slave)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--link-a", help="lien symbolique vers le premier port")
    ap.add_argument("--link-b", help="lien symbolique vers le second port")
    args = ap.parse_args()

    master_a, slave_a, name_a = make_pty()
    master_b, slave_b, name_b = make_pty()
    # Les descripteurs "slave" restent ouverts ici pour que les ports ne se ferment pas
    # quand un programme se déconnecte.
    keep_open = (slave_a, slave_b)

    links = []
    for link, target in ((args.link_a, name_a), (args.link_b, name_b)):
        if link:
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(target, link)
            links.append(link)
    print(f"A={name_a} B={name_b}", flush=True)

    try:
        while True:
            ready, _, _ = select.select([master_a, master_b], [], [])
            for fd in ready:
                data = os.read(fd, 4096)
                if data:
                    os.write(master_b if fd == master_a else master_a, data)
    except KeyboardInterrupt:
        pass
    finally:
        for link in links:
            if os.path.islink(link):
                os.remove(link)
        del keep_open


if __name__ == "__main__":
    main()
