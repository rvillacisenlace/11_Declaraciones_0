"""Verificacion del comprobante oficial: es la UNICA prueba valida de que una declaracion se envio.
Se lee el PDF descargado, se comprueba contra lo esperado y solo entonces se archiva con su nombre definitivo:
    numerodeserie_ruc_fechahoradescarga.pdf   (la fecha y hora van juntas: AAAAMMDDHHMMSS)"""
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from src.utils.exceptions import ComprobanteInvalido
from src.utils.logger import get_logger
from src.utils.validators import enmascarar_ruc, hoy_ecuador, nombre_mes

log = get_logger(__name__)


@dataclass(frozen=True)
class Comprobante:
    serie: str
    ruc: str
    fecha_declaracion: datetime
    periodo: str  # p. ej. "OCTUBRE 2026"
    impuesto: str
    tipo: str  # ORIGINAL / SUSTITUTIVA
    sin_valor_a_pagar: bool


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


def parsear(texto: str) -> Comprobante:
    def buscar(patron: str, campo: str, flags: int = 0):
        m = re.search(patron, texto, re.I | flags)
        if not m:
            raise ComprobanteInvalido(f"No se pudo leer '{campo}' del comprobante")
        return m

    serie = buscar(r"N[uú]mero de serie:\s*(\d{8,})", "numero de serie").group(1)
    fecha = buscar(r"(\d{2}/\d{2}/\d{4})\s+a\s+las\s+(\d{2}:\d{2}:\d{2})", "fecha y hora de declaracion")
    ruc = buscar(r"\b(\d{13})\b", "identificacion").group(1)
    periodo = buscar(r"Per[ií]odo fiscal:\s*([^\W\d_]+\s+\d{4})", "periodo fiscal").group(1)
    impuesto = buscar(r"Impuesto:\s*([^\n]+(?:\n(?!Tipo de|Declaraci[oó]n sin)[^\n:]+)?)", "impuesto").group(1)  # a veces ocupa 2 lineas
    tipo = buscar(r"Tipo de declaraci[oó]n:\s*([^\n]+)", "tipo de declaracion").group(1)
    return Comprobante(
        serie=serie, ruc=ruc,
        fecha_declaracion=datetime.strptime(f"{fecha.group(1)} {fecha.group(2)}", "%d/%m/%Y %H:%M:%S"),
        periodo=_norm(periodo), impuesto=_norm(impuesto), tipo=_norm(tipo),
        sin_valor_a_pagar="SIN VALOR A PAGAR" in _norm(texto),
    )


def leer_pdf(ruta: Path) -> Comprobante:
    datos = Path(ruta).read_bytes()
    if not datos.startswith(b"%PDF"):  # p. ej. una pagina de bloqueo guardada como si fuera PDF
        raise ComprobanteInvalido("El archivo descargado no es un PDF")
    try:
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(Path(ruta)).pages)
    except (PyPdfError, ValueError, KeyError):
        raise ComprobanteInvalido("El PDF descargado no se pudo leer") from None
    if not texto.strip():
        raise ComprobanteInvalido("El PDF descargado no tiene texto legible")
    return parsear(texto)


def verificar(c: Comprobante, ruc_esperado: str, periodo: tuple[int, int], hoy: date | None = None,
              impuesto: str = "2011") -> None:
    """Lanza ComprobanteInvalido si algo no coincide. El mensaje nunca incluye el RUC."""
    problemas = []
    if c.ruc != ruc_esperado:
        problemas.append("el RUC del comprobante no es el esperado")
    if c.periodo != f"{nombre_mes(periodo[1]).upper()} {periodo[0]}":
        problemas.append(f"el periodo es {c.periodo} y se esperaba {nombre_mes(periodo[1]).upper()} {periodo[0]}")
    if not c.impuesto.startswith(impuesto):
        problemas.append(f"el impuesto es '{c.impuesto}' y se esperaba el {impuesto}")
    if c.tipo != "ORIGINAL":
        problemas.append(f"el tipo de declaracion es {c.tipo} y se esperaba ORIGINAL")
    if not c.sin_valor_a_pagar:
        problemas.append("el comprobante NO dice 'sin valor a pagar': la declaracion no fue en cero")
    if c.fecha_declaracion.date() != (hoy or hoy_ecuador()):
        problemas.append("la fecha de declaracion no es la de hoy: puede ser un comprobante antiguo")
    if problemas:
        raise ComprobanteInvalido("; ".join(problemas))


def periodo_de(c: Comprobante) -> tuple[int, int]:
    """Periodo del comprobante como (anio, mes); p. ej. 'OCTUBRE 2026' -> (2026, 10)."""
    nombre, anio = c.periodo.rsplit(" ", 1)
    for mes in range(1, 13):
        if _norm(nombre_mes(mes)) == nombre:
            return int(anio), mes
    raise ComprobanteInvalido(f"No se reconoce el periodo del comprobante: {c.periodo}")


def nombre_archivo(c: Comprobante, descarga: datetime) -> str:
    return f"{c.serie}_{c.ruc}_{descarga:%Y%m%d%H%M%S}.pdf"


def archivar(descargado: Path, destino: Path, ruc_esperado: str, periodo: tuple[int, int],
             ahora: datetime | None = None, hoy: date | None = None, impuesto: str = "2011") -> Path:
    """Verifica el PDF y lo mueve a 'destino' con su nombre definitivo. Si no pasa la verificacion no se mueve."""
    c = leer_pdf(descargado)
    verificar(c, ruc_esperado, periodo, hoy, impuesto)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    final = destino / nombre_archivo(c, ahora or datetime.now())
    if final.exists():
        raise ComprobanteInvalido("Ya existe un comprobante con ese nombre")
    shutil.move(str(descargado), str(final))
    log.info("Comprobante archivado: serie %s (RUC %s)", c.serie, enmascarar_ruc(c.ruc))  # el nombre del archivo lleva el RUC completo
    return final