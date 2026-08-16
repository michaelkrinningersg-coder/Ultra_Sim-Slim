"""PyInstaller-Einstiegspunkt für die ausgelieferte EXE.

Bewusst eine eigene Datei im Wurzelverzeichnis: PyInstaller braucht ein
Skript, kein Modul, und dieses hier tut nichts außer die eigentliche
Startlogik aus ``ultraslim.app`` aufzurufen.
"""

import multiprocessing
import sys

from ultraslim.app import main

if __name__ == "__main__":
    # Ohne diesen Aufruf startet ein eingefrorenes Programm unter Windows
    # bei jedem Subprozess eine weitere Kopie seiner selbst.
    multiprocessing.freeze_support()
    sys.exit(main())
