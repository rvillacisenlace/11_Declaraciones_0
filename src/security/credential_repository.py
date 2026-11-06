"""Lee credenciales del Excel cifrado (formato real):
  hoja 'Accesos' : ID fideicomiso | Usuario SRI | Contrasena SRI | Correo   (el usuario es el RUC del fideicomiso)
  hoja 'Contador': Usuario SRI | Contrasena SRI                             (UNA fila: firma todos los fideicomisos)
El cruce con el Control es por RUC (Usuario SRI == RUC): los ID de ambos archivos se numeraron por separado."""
import re
import unicodedata
from dataclasses import dataclass, field

from openpyxl import load_workbook

from config import settings
from src.security.workbook_decryption import abrir_en_memoria
from src.utils.exceptions import ConfigError
from src.utils.logger import get_logger
from src.utils.validators import enmascarar_ruc

log = get_logger(__name__)

HOJA_ACCESOS = "Accesos"
HOJA_CONTADOR = "Contador"
COL_USUARIO = "usuario_sri"
COL_CLAVE = "contrasena_sri"


@dataclass(frozen=True)
class Credencial:
    id: str
    tipo: str
    ruc: str
    clave: str = field(repr=False)  # repr oculto: no sale en logs ni tracebacks
    contador_id: str | None = None

    def __str__(self) -> str:
        return f"{self.tipo}:{self.id}({enmascarar_ruc(self.ruc)})"


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "_", t.strip().lower())


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _abrir(password: str):
    if settings.CREDENCIALES_XLSX is None:
        raise ConfigError("Falta CREDENCIALES_XLSX en el .env")
    return load_workbook(abrir_en_memoria(settings.CREDENCIALES_XLSX, password), read_only=True, data_only=True)


def _filas(libro, hoja: str) -> list[dict]:
    if hoja not in libro.sheetnames:
        raise ConfigError(f"Falta la hoja '{hoja}' en el archivo de credenciales")
    it = libro[hoja].iter_rows(values_only=True)
    enc = [_norm(c) for c in next(it, ())]
    if COL_USUARIO not in enc or COL_CLAVE not in enc:
        raise ConfigError(f"La hoja '{hoja}' debe tener las columnas 'Usuario SRI' y 'Contrasena SRI'")
    pu, pc = enc.index(COL_USUARIO), enc.index(COL_CLAVE)
    return [{COL_USUARIO: _texto(f[pu]) if pu < len(f) else "", COL_CLAVE: _texto(f[pc]) if pc < len(f) else ""}
            for f in it]


def cargar_contribuyente(id_control: str, ruc: str, password: str) -> Credencial:
    """Credencial del fideicomiso cuyo RUC (segun el Control) coincide con 'Usuario SRI'."""
    libro = _abrir(password)
    try:
        filas = [f for f in _filas(libro, HOJA_ACCESOS) if f[COL_USUARIO] == ruc]
    finally:
        libro.close()
    claves = {f[COL_CLAVE] for f in filas}
    if not filas:
        raise ConfigError(f"No hay credencial para el RUC del fideicomiso {id_control}")
    if len(claves) != 1:
        raise ConfigError(f"Credencial ambigua para el fideicomiso {id_control}: "
                          f"{len(filas)} filas con ese usuario y claves distintas")
    clave = claves.pop()
    if not clave:
        raise ConfigError(f"La credencial del fideicomiso {id_control} no tiene clave")
    cred = Credencial(id=id_control, tipo="contribuyente", ruc=ruc, clave=clave)
    log.info("Credencial cargada: %s", cred)
    return cred


def cargar_contador(password: str) -> Credencial:
    """Credencial del contador que firma todas las declaraciones (hoja 'Contador', exactamente 1 fila)."""
    libro = _abrir(password)
    try:
        filas = [f for f in _filas(libro, HOJA_CONTADOR) if f[COL_USUARIO] or f[COL_CLAVE]]
    finally:
        libro.close()
    if len(filas) != 1:
        raise ConfigError(f"La hoja '{HOJA_CONTADOR}' debe tener exactamente 1 fila y tiene {len(filas)}")
    ruc, clave = filas[0][COL_USUARIO], filas[0][COL_CLAVE]
    if not re.fullmatch(r"\d{13}", ruc):
        raise ConfigError("El RUC del contador debe tener 13 digitos")
    if not clave:
        raise ConfigError("El contador no tiene clave")
    cred = Credencial(id="contador", tipo="contador", ruc=ruc, clave=clave)
    log.info("Credencial cargada: %s", cred)
    return cred


def auditar(rucs: list[str], password: str) -> dict[str, str]:
    """Para cada RUC devuelve el motivo por el que su credencial NO es utilizable. No conserva ni devuelve claves."""
    libro = _abrir(password)
    try:
        por_usuario: dict[str, set] = {}
        for f in _filas(libro, HOJA_ACCESOS):
            por_usuario.setdefault(f[COL_USUARIO], set()).add(f[COL_CLAVE])
    finally:
        libro.close()
    problemas = {}
    for ruc in rucs:
        claves = por_usuario.get(ruc)
        if not claves:
            problemas[ruc] = "sin credencial en Accesos"
        elif len(claves) > 1:
            problemas[ruc] = "credencial ambigua (claves distintas para el mismo usuario)"
        elif not next(iter(claves)):
            problemas[ruc] = "credencial sin clave"
    return problemas
