"""Donde se guarda cada cosa (todo cuelga de ZERO_DOCS):
    Declaraciones/<Responsable>/<RUC>/<MM-AAAA>/<codigo - impuesto>/<serie>_<ruc>_<fecha>.pdf
    Evidencias/<Responsable>/<RUC>/<MM-AAAA>/<codigo - impuesto>/<AAAA-MM>_<impuesto>_<paso>_<fecha>_<hora>.png
El responsable sale de la columna RESPONSABLE del Control. Los nombres con acentos usan escapes unicode para no
depender de la codificacion con que se guarde este archivo."""
import re
from pathlib import Path

from config import settings
from src.utils.exceptions import ConfigError

IMPUESTOS = {
    "2011": "2011 - Declaraci\u00f3n de IVA",
    "1031": "1031 - Declaraci\u00f3n de retenciones en la fuente",
}
SIN_RESPONSABLE = "SIN RESPONSABLE"
SIN_RUC = "SIN RUC"

_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def nombre_carpeta(texto, vacio: str = SIN_RESPONSABLE) -> str:
    """Convierte un valor del Control en un nombre de carpeta valido en Windows. Nunca puede salirse de su nivel
    (sin barras ni '..'). Si queda vacio devuelve 'vacio'."""
    t = _INVALIDOS.sub("_", str(texto or ""))
    t = re.sub(r"\s+", " ", t).strip(" .")
    if not t.strip("_ "):
        return vacio
    if t.split(".")[0].upper() in _RESERVADOS:
        t += "_"
    return t[:60].rstrip(" .")


def nombre_periodo(periodo: tuple[int, int]) -> str:
    """Carpeta del periodo declarado: MM-AAAA (p. ej. (2026, 10) -> '10-2026')."""
    return f"{periodo[1]:02d}-{periodo[0]}"


def carpeta_declaracion(responsable, ruc: str, codigo: str, periodo: tuple[int, int]) -> Path:
    if codigo not in IMPUESTOS:
        raise ConfigError(f"Impuesto desconocido: {codigo}")
    return (settings.DECLARACIONES_DIR / nombre_carpeta(responsable) / nombre_carpeta(ruc, SIN_RUC)
            / nombre_periodo(periodo) / IMPUESTOS[codigo])


def carpeta_evidencia(responsable, ruc: str, periodo: tuple[int, int], codigo: str) -> Path:
    if codigo not in IMPUESTOS:
        raise ConfigError(f"Impuesto desconocido: {codigo}")
    return (settings.EVIDENCE_DIR / nombre_carpeta(responsable) / nombre_carpeta(ruc, SIN_RUC)
            / nombre_periodo(periodo) / IMPUESTOS[codigo])