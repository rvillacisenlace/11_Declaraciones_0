"""Capturas de pantalla: evidence/{contribuyente}/{AAAA-MM}/{paso}_{timestamp}.png"""
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from config import settings
from src.utils.logger import get_logger

log = get_logger(__name__)


def capturar(page: Page, contribuyente: str, periodo: tuple[int, int], paso: str) -> Path:
    carpeta = settings.EVIDENCE_DIR / contribuyente / f"{periodo[0]}-{periodo[1]:02d}"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{paso}_{datetime.now():%Y%m%d_%H%M%S}.png"
    page.screenshot(path=str(ruta), full_page=True)
    log.info("Evidencia guardada: %s", ruta.name)
    return ruta
