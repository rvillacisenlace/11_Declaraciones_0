"""Capturas de pantalla: <carpeta de evidencias del RUC>/<AAAA-MM>_<impuesto>_<paso>_<fecha>_<hora>.png
Se toman SOLO justo antes de un clic que cambia de pantalla (Siguiente, Aceptar, Imprimir), mas la de error."""
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from src.utils.logger import get_logger

log = get_logger(__name__)


def capturar(page: Page, carpeta: Path, periodo: tuple[int, int], paso: str, impuesto: str = "2011") -> Path:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{periodo[0]}-{periodo[1]:02d}_{impuesto}_{paso}_{datetime.now():%Y%m%d_%H%M%S}.png"
    page.screenshot(path=str(ruta), full_page=True)
    log.info("Evidencia guardada: %s", ruta.name)
    return ruta