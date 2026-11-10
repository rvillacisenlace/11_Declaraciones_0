"""Donde se guarda cada cosa. Comprobantes: <Declaraciones>/<RUC>/<codigo - impuesto>/. Capturas: Evidencias/.
Los nombres de carpeta usan escapes unicode para no depender de la codificacion con que se guarde este archivo."""
from pathlib import Path

from config import settings
from src.utils.exceptions import ConfigError

IMPUESTOS = {
    "2011": "2011 - Declaraci\u00f3n de IVA",
    "1031": "1031 - Declaraci\u00f3n de retenciones en la fuente",
}


def carpeta_declaracion(ruc: str, codigo: str) -> Path:
    if codigo not in IMPUESTOS:
        raise ConfigError(f"Impuesto desconocido: {codigo}")
    return settings.DECLARACIONES_DIR / ruc / IMPUESTOS[codigo]