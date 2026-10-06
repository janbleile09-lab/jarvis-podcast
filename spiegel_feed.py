#!/usr/bin/env python3
"""spiegle_feed.py — macht den JARVIS-Podcast-Feed ÖFFENTLICH für Apple Podcasts.

WARUM / PROBLEM, das dieses Skript löst:
Der Feed wird vom Hub (`~/jarvis-briefing-hub`) erzeugt und enthält **absolute** URLs auf
`http://192.168.178.119:8000/...` — eine LAN-Adresse. Apple Podcasts (und jedes andere
Podcast-Programm auf dem iPhone) kann die NICHT abrufen. Der Feed war damit nur im eigenen
WLAN hörbar.

LÖSUNG: Der Feed und die Audiodateien werden in ein ÖFFENTLICHES GitHub-Repository gelegt
(GitHub Pages). Der gespiegelte Feed enthält nur relative/öffentliche HTTPS-Adressen. Nichts
am Hub wird verändert, nichts wird gelöscht — es entsteht eine reine Kopie nach außen.

Aufruf:
    python3 spiegel_feed.py                 # spiegeln (Standard)
    python3 spiegel_feed.py --pruefen       # nur prüfen, nichts schreiben
    python3 spiegel_feed.py --nur-neue      # Dateien, die schon da sind, nicht erneut laden

Die Geheimnisse (Key-Parameter) werden ENTFERNT: der Feed soll öffentlich sein, ein Zugangs-
schlüssel in einer öffentlichen Datei wäre ein Widerspruch. Die Audio-Dateien selbst sind
unbedenklich — es sind Jans eigene Sprachaufnahmen über sein Projekt.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOKAL = "http://127.0.0.1:8000"
ZIEL = Path.home() / "jarvis-podcast-public"
REPO = "janbleile09-lab/jarvis-podcast"
BRANCH = "gh-pages"
# Wird nach dem ersten Push automatisch ermittelt und hier abgelegt:
BASIS_DATEI = ZIEL / ".oeffentliche_basis"


def hol(url: str, ziel: Path | None = None, timeout: int = 60):
    """Holt eine URL. Gibt Bytes zurück oder schreibt sie in eine Datei."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        daten = r.read()
    if ziel:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(daten)
    return daten


def feed_holen() -> str:
    return hol(f"{LOKAL}/podcast.xml").decode("utf-8")


def oeffentliche_basis() -> str:
    if BASIS_DATEI.exists():
        return BASIS_DATEI.read_text().strip()
    # Aus dem Repo ableiten, ohne zu raten
    return f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}"


def feed_umbauen(xml: str, basis: str) -> tuple[str, list[str]]:
    """Absolute LAN-Adressen -> öffentliche HTTPS-Adressen. Keys werden entfernt.

    Rückgabe: (neuer Feed, Liste der Audiodateien, die geholt werden müssen)
    """
    dateien: list[str] = []

    def ersetze(m: re.Match) -> str:
        pfad = m.group(1)  # z. B. audio/podcast_....mp3 oder cover.png
        dateien.append(pfad)
        return f"{basis}/{pfad}"

    # Alle http://192.168.178.119:8000/<pfad>?key=... -> <basis>/<pfad>
    neu = re.sub(
        r"http://192\.168\.178\.119:8000/([A-Za-z0-9_./-]+)(?:\?[^\"'>\s]*)?",
        ersetze,
        xml,
    )
    # Falls im Feed lokale Adressen mit 127.0.0.1 stehen
    neu = re.sub(
        r"http://127\.0\.0\.1:8000/([A-Za-z0-9_./-]+)(?:\?[^\"'>\s]*)?",
        ersetze,
        neu,
    )
    # Restliche nackte LAN-Adressen OHNE Pfad (die <link>-Einträge je Folge).
    # Erst NACH dem Datei-Umbau, sonst würde die Datei-Ersetzung zerstört.
    neu = neu.replace("http://192.168.178.119:8000", basis)
    neu = neu.replace("http://127.0.0.1:8000", basis)
    # Der Kanal-Link soll auf die öffentliche Feed-Adresse zeigen
    neu = re.sub(r"<link>[^<]*</link>", f"<link>{basis}/</link>", neu, count=1)
    return neu, sorted(set(dateien))


def pruefe_feed(xml: str) -> list[str]:
    """Findet Probleme im umgebauten Feed. Leere Liste = in Ordnung."""
    fehler = []
    if "192.168.178.119" in xml:
        fehler.append("LAN-Adresse noch im Feed")
    if "127.0.0.1" in xml:
        fehler.append("localhost noch im Feed")
    if "?key=" in xml:
        fehler.append("Zugangsschlüssel noch im Feed")
    if "<enclosure" not in xml:
        fehler.append("keine Audio-Anhänge (<enclosure>) im Feed")
    n = xml.count("<item>")
    if n == 0:
        fehler.append("keine Folgen im Feed")
    return fehler


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ZIEL, capture_output=True, text=True, check=check)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruefen", action="store_true", help="nur anzeigen, nichts schreiben")
    ap.add_argument("--nur-neue", action="store_true", help="vorhandene Audio-Dateien nicht erneut laden")
    args = ap.parse_args()

    basis = oeffentliche_basis()
    print(f"Öffentliche Basis: {basis}")

    roh = feed_holen()
    print(f"Feed vom Hub geholt: {len(roh)} Zeichen, {roh.count('<item>')} Folgen")

    neu, dateien = feed_umbauen(roh, basis)
    print(f"Adressen umgeschrieben, {len(dateien)} Dateien referenziert")

    fehler = pruefe_feed(neu)
    if fehler:
        print("FEHLER im umgebauten Feed:")
        for f in fehler:
            print("  -", f)
        return 2
    print("Prüfung: Feed ist öffentlich verwendbar (keine LAN-Adresse, kein Schlüssel)")

    if args.pruefen:
        print("\n--- Vorschau der ersten Folge ---")
        m = re.search(r"<item>.*?</item>", neu, re.S)
        print(m.group(0)[:700] if m else "(keine Folge)")
        return 0

    ZIEL.mkdir(parents=True, exist_ok=True)

    # 1) Feed schreiben
    (ZIEL / "podcast.xml").write_text(neu, encoding="utf-8")
    (ZIEL / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>JARVIS Podcast</title>"
        f"<p>Podcast-Feed: <a href='podcast.xml'>podcast.xml</a></p>",
        encoding="utf-8",
    )
    # Apple Podcasts braucht eine Abschaltdatei, damit der Rest nicht indexiert wird
    (ZIEL / ".nojekyll").write_text("", encoding="utf-8")

    # 2) Dateien holen — bevorzugt direkt von der Platte (schnell, keine Doppelladung),
    #    sonst über den Hub.
    HUB_AUDIO = Path.home() / "jarvis-briefing-hub" / "data" / "audio"
    geholt = 0
    uebersprungen = 0
    fehlgeschlagen = []
    for pfad in dateien:
        ziel = ZIEL / pfad
        if args.nur_neue and ziel.exists() and ziel.stat().st_size > 0:
            uebersprungen += 1
            continue
        quelle = HUB_AUDIO / Path(pfad).name
        if quelle.is_file() and quelle.stat().st_size > 0:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_bytes(quelle.read_bytes())
            geholt += 1
            continue
        try:
            hol(f"{LOKAL}/{pfad}", ziel)
            geholt += 1
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            fehlgeschlagen.append((pfad, str(exc)[:80]))
    print(f"Dateien: {geholt} geholt, {uebersprungen} übersprungen, {len(fehlgeschlagen)} fehlgeschlagen")
    for p, e in fehlgeschlagen:
        print(f"  ! {p}: {e}")

    # 3) Größe und Inhalt prüfen — vor dem Push
    gesamt = sum(f.stat().st_size for f in ZIEL.rglob("*") if f.is_file())
    print(f"Gesamtgröße: {gesamt / 1024 / 1024:.1f} MB")

    for pfad in dateien:
        ziel = ZIEL / pfad
        if ziel.exists() and ziel.stat().st_size == 0:
            print(f"FEHLER: {pfad} ist leer")
            return 3

    print("\nFertig. Dateien liegen in", ZIEL)
    print("Nächster Schritt: hochladen mit --hochladen (macht der Auftraggeber).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
