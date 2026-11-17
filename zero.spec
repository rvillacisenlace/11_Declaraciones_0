# -*- mode: python ; coding: utf-8 -*-
# Construir:  py -m PyInstaller zero.spec --clean      Resultado: dist\Zero.exe
import os

import playwright
from PyInstaller.utils.hooks import collect_all

NOMBRE = "Zero"
ENTRADA = "zero_app.py"  # linea de comandos (con consola)
ICONO = "assets/zero_icono.ico"  # opcional: si no existe se construye sin icono

# El driver de Playwright (Node.js + JS) no son imports de Python: PyInstaller no lo detecta.
RUTA_DRIVER = os.path.join(os.path.dirname(playwright.__file__), "driver")

datas = [(RUTA_DRIVER, "playwright/driver")]
binaries = []
# main, config y src se importan dentro de funciones o como paquetes: se piden de forma explicita.
hiddenimports = ["main", "truststore", "msal", "msoffcrypto", "openpyxl", "pypdf", "tzdata"]

# collect_all trae submodulos y archivos de datos de paquetes que los leen en ejecucion.
for paquete in ("playwright", "tzdata"):  # msal/msoffcrypto: basta el analisis normal (su __main__ arrastraba pkg_resources)
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

# Paquetes instalados en la maquina que Zero no usa: inflan el .exe.
EXCLUIDOS = ["pandas", "numpy", "matplotlib", "scipy", "IPython", "jupyter", "notebook",
             "pytest", "_pytest", "pytest_playwright", "pkg_resources", "setuptools", "tkinter"]

a = Analysis([ENTRADA], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=EXCLUIDOS, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name=NOMBRE, debug=False, bootloader_ignore_signals=False, strip=False,
          upx=True, upx_exclude=[], runtime_tmpdir=None,
          console=True,  # la contrasena y la confirmacion se piden por teclado
          disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
          codesign_identity=None, entitlements_file=None,
          icon=ICONO if os.path.isfile(ICONO) else None)
