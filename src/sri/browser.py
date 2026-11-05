"""Edge real lanzado como proceso normal; Playwright se conecta por CDP (como en Archivist).
Nunca headless: empeora las huellas y elimina el respaldo manual."""
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from config import settings
from src.utils.exceptions import ConfigError
from src.utils.logger import get_logger

log = get_logger(__name__)

_EDGE = (
    Path(os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.getenv("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
)


def _find_edge() -> Path:
    for ruta in _EDGE:
        if ruta.is_file():
            return ruta
    raise ConfigError("No se encontro Microsoft Edge en las rutas estandar")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, proc: subprocess.Popen, timeout_s: float = 20.0) -> None:
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        if proc.poll() is not None:
            raise ConfigError(
                f"Edge termino al arrancar (codigo {proc.returncode}). Si hay otra ventana de Edge "
                "abierta con el perfil de Zero, cierrela y reintente."
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise ConfigError(f"Edge no abrio el puerto de depuracion en {timeout_s:.0f} s")


def _cerrar_edge(browser: Browser, proc: subprocess.Popen) -> None:
    """Cierre ordenado: Edge guarda las cookies del perfil al salir."""
    try:
        browser.new_browser_cdp_session().send("Browser.close")
    except Exception as e:
        log.warning("No se pudo cerrar Edge por CDP: %s", type(e).__name__)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@contextmanager
def open_context() -> Iterator[BrowserContext]:
    settings.ensure_dirs()
    port = _free_port()
    proc = subprocess.Popen([
        str(_find_edge()),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={settings.AUTH_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
    ])
    try:
        _wait_port(port, proc)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            context.set_default_timeout(settings.DEFAULT_TIMEOUT_MS)
            try:
                yield context
            finally:
                _cerrar_edge(browser, proc)
    finally:
        if proc.poll() is None:
            proc.kill()
