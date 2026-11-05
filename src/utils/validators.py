"""Funciones puras: periodo, mascaras y limpieza de texto."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ_EC = ZoneInfo("America/Guayaquil")
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre")


def hoy_ecuador() -> date:
    """Fecha en Ecuador, no la del reloj de la PC."""
    return datetime.now(TZ_EC).date()


def periodo_a_declarar(hoy: date | None = None) -> tuple[int, int]:
    """(anio, mes) del mes anterior al que esta en curso."""
    hoy = hoy or hoy_ecuador()
    return (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)


def nombre_mes(mes: int) -> str:
    return MESES[mes - 1]


def enmascarar_ruc(ruc: str) -> str:
    return f"{ruc[:4]}***{ruc[-3:]}" if len(ruc) >= 10 else "***"


def url_corta(url: str) -> str:
    """Sin query, fragmento ni ;jsessionid."""
    return re.split(r"[?#;]", url, maxsplit=1)[0]


def enmascarar_digitos(texto: str) -> str:
    """Oculta secuencias largas de digitos (RUC, cedulas)."""
    return re.sub(r"\d{10,}", "***", texto)