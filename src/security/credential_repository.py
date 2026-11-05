"""Lee credenciales del Excel cifrado. Hoja 'Credenciales', columnas:
   id | tipo (contribuyente/contador) | ruc | clave | contador_id (solo contribuyentes)
Solo se extrae la fila pedida; el libro no se conserva."""
from dataclasses import dataclass, field

from openpyxl import load_workbook

from config import settings
from src.security.workbook_decryption import abrir_en_memoria
from src.utils.exceptions import ConfigError
from src.utils.logger import get_logger
from src.utils.validators import enmascarar_ruc

log = get_logger(__name__)

HOJA = "Credenciales"
COLUMNAS = ("id", "tipo", "ruc", "clave", "contador_id")


@dataclass(frozen=True)
class Credencial:
    id: str
    tipo: str
    ruc: str
    clave: str = field(repr=False)  # repr oculto: no sale en logs ni tracebacks
    contador_id: str | None = None

    def __str__(self) -> str:
        return f"{self.tipo}:{self.id}({enmascarar_ruc(self.ruc)})"


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def cargar(id_: str, password_maestra: str) -> Credencial:
    if settings.CREDENCIALES_XLSX is None:
        raise ConfigError("Falta CREDENCIALES_XLSX en el .env")
    libro = load_workbook(abrir_en_memoria(settings.CREDENCIALES_XLSX, password_maestra),
                          read_only=True, data_only=True)
    try:
        if HOJA not in libro.sheetnames:
            raise ConfigError(f"Falta la hoja '{HOJA}' en el archivo de credenciales")
        filas = libro[HOJA].iter_rows(values_only=True)
        encabezado = [_texto(c).lower() for c in next(filas, ())]
        faltan = [c for c in COLUMNAS if c not in encabezado]
        if faltan:
            raise ConfigError(f"Faltan columnas en '{HOJA}': {', '.join(faltan)}")
        pos = {c: encabezado.index(c) for c in COLUMNAS}
        coincidencias = []
        for fila in filas:
            if _texto(fila[pos["id"]]) == id_:
                coincidencias.append(fila)
        if len(coincidencias) != 1:
            raise ConfigError(f"El id '{id_}' aparece {len(coincidencias)} veces en '{HOJA}' (debe ser 1)")
        f = coincidencias[0]
        cred = Credencial(
            id=id_, tipo=_texto(f[pos["tipo"]]).lower(), ruc=_texto(f[pos["ruc"]]),
            clave=_texto(f[pos["clave"]]), contador_id=_texto(f[pos["contador_id"]]) or None,
        )
    finally:
        libro.close()
    if not cred.ruc or not cred.clave:
        raise ConfigError(f"El id '{id_}' no tiene RUC o clave completos")
    log.info("Credencial cargada: %s", cred)
    return cred
