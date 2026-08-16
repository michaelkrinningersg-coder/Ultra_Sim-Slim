# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Beschreibung für UltraSim Slim.

Was mit ins Bündel muss und warum:

* ``ultraslim/web/templates`` und ``ultraslim/web/static`` — Jinja2 und
  StaticFiles lesen sie zur Laufzeit von der Platte, PyInstaller findet
  sie deshalb nicht von allein.

Was bewusst **nicht** mitkommt: Streckendaten. Die Höhenprofile werden
beim Start aus Seed und Archetyp erzeugt, nicht geladen — die EXE
braucht dadurch weder Kartendaten noch Netz, und sie bleibt klein.
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("ultraslim/web/templates", "ultraslim/web/templates"),
    ("ultraslim/web/static", "ultraslim/web/static"),
]

# uvicorn lädt seine Protokoll- und Loop-Implementierungen über
# Zeichenketten nach; im Quelltext steht davon nichts, was PyInstaller
# sehen könnte.
hiddenimports = collect_submodules("uvicorn") + [
    "ultraslim.web.main",
    "ultraslim.web.rooms",
]

a = Analysis(
    ["ultraslim_app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["scipy", "matplotlib", "pandas", "tkinter", "PIL", "pytest", "httpx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="UltraSimSlim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
