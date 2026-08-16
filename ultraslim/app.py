"""Startlogik der ausgelieferten Anwendung.

Ein Doppelklick auf die EXE soll ein Fenster mit dem Hauptmenü öffnen,
sonst nichts. Dafür braucht es drei Dinge: einen freien Port, einen
Server darauf und einen Browser, der ihn aufruft.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8420


def _writable_data_dir(explicit: str | None) -> Path:
    """Wohin die Ergebnisse geschrieben werden.

    Neben der EXE, solange das geht — dann liegt eine Saison dort, wo
    der Nutzer sie vermutet. Ist der Ordner schreibgeschützt (Programme,
    USB-Stick, Netzlaufwerk), weicht die Anwendung ins Benutzerprofil
    aus, statt beim ersten Rennen abzustürzen.
    """
    if explicit:
        path = Path(explicit).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    beside = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    candidate = beside / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".schreibtest"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        fallback = Path.home() / "UltraSimSlim" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _free_port(preferred: int) -> int:
    """Der Wunschport, sonst irgendeiner.

    Beim zweiten Start ist der erste noch belegt — daran soll die
    Anwendung nicht scheitern.
    """
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
            except OSError:
                continue
    return preferred


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="UltraSimSlim", description="Ultracycling-Simulator, schlanke Fassung"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data", default=None, help="Ordner für Ergebnisse")
    parser.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")
    args = parser.parse_args(argv)

    import uvicorn

    from .web.main import create_app

    data_dir = _writable_data_dir(args.data)
    port = _free_port(args.port) if args.host == "127.0.0.1" else args.port
    url = f"http://{args.host}:{port}/"

    print("UltraSim Slim")
    print(f"  Ergebnisse: {data_dir}")
    print(f"  Oberfläche: {url}")
    print("  Beenden mit Strg+C.")

    if not args.no_browser:
        # Erst nach kurzer Verzögerung, sonst öffnet der Browser die
        # Seite, bevor der Server auf dem Port sitzt.
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run(create_app(data_dir), host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
