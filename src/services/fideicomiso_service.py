"""Lee la hoja 'Fideicomisos' del Control y decide cuales se procesan.
Regla: nunca se adivina. Todo lo dudoso se EXCLUYE con motivo; declarar de menos es mejor que declarar de mas."""
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from src.security import credential_repository
from src.utils.exceptions import ConfigError
from src.utils.logger import get_logger

log = get_logger(__name__)

HOJA = "Fideicomisos"
COLUMNAS = ("id", "nombre", "ruc", "declara_0", "responsable")


@dataclass(frozen=True)
class Fideicomiso:
    fila: int
    id: str
    nombre: str
    ruc: str
    responsable: str


@dataclass(frozen=True)
class Excluido:
    fila: int
    id: str
    motivo: str


@dataclass(frozen=True)
class ResultadoControl:
    total: int
    omitidos: int  # DECLARA_0 = NO o vacio
    pendientes: list
    excluidos: list


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", "_", t.strip().lower())


def _txt(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def leer_control(ruta: Path) -> ResultadoControl:
    if ruta is None:
        raise ConfigError("Falta CONTROL_XLSX en el .env")
    if not Path(ruta).is_file():
        raise ConfigError(f"No se encontro el archivo de control: {Path(ruta).name} (revise la ruta en CONTROL_XLSX)")
    try:
        libro = load_workbook(ruta, read_only=True, data_only=True)
    except PermissionError:
        raise ConfigError("No se pudo leer el archivo de control: esta bloqueado por otro programa") from None
    try:
        if HOJA not in libro.sheetnames:
            raise ConfigError(f"Falta la hoja '{HOJA}' en el archivo de control")
        filas = libro[HOJA].iter_rows(values_only=True)
        encabezado = [_norm(c) for c in next(filas, ())]
        faltan = [c for c in COLUMNAS if c not in encabezado]
        if faltan:
            raise ConfigError(f"Faltan columnas en '{HOJA}': {', '.join(faltan)}")
        pos = {c: encabezado.index(c) for c in COLUMNAS}
        datos = []
        for n, f in enumerate(filas, start=2):
            if all(_txt(c) == "" for c in f):
                continue  # fila totalmente vacia
            datos.append((n, {c: _txt(f[i]) if i < len(f) else "" for c, i in pos.items()}))
    finally:
        libro.close()

    ids = Counter(d["id"] for _, d in datos if d["id"])
    rucs = Counter(d["ruc"] for _, d in datos if d["ruc"])
    pendientes, excluidos, omitidos = [], [], 0
    for n, d in datos:
        marca = _norm(d["declara_0"])
        if marca in ("no", ""):
            omitidos += 1
            continue
        motivos = []
        if marca != "si":
            motivos.append("DECLARA_0 con valor no reconocido")
        if not d["id"]:
            motivos.append("ID vacio")
        elif ids[d["id"]] > 1:
            motivos.append("ID repetido")
        if not re.fullmatch(r"\d{13}", d["ruc"]):
            motivos.append("RUC invalido (se esperan 13 digitos)")
        elif rucs[d["ruc"]] > 1:
            motivos.append("RUC repetido en el Control")
        if motivos:
            excluidos.append(Excluido(n, d["id"], "; ".join(motivos)))
            log.warning("Fila %d excluida (id=%s): %s", n, d["id"] or "-", "; ".join(motivos))
        else:
            pendientes.append(Fideicomiso(n, d["id"], d["nombre"], d["ruc"], d["responsable"]))
    log.info("Control leido: %d filas, %d omitidas, %d pendientes, %d excluidas",
             len(datos), omitidos, len(pendientes), len(excluidos))
    return ResultadoControl(len(datos), omitidos, pendientes, excluidos)


def ruta_control():
    """Ruta local del Control (CONTROL_XLSX en el .env) mientras no exista Graph."""
    valor = os.getenv("CONTROL_XLSX", "")
    return Path(valor) if valor else None


def cruzar_credenciales(pendientes: list, password: str):
    """Cruce por RUC (Usuario SRI == RUC). Devuelve (listos, excluidos_adicionales); no conserva claves."""
    problemas = credential_repository.auditar([p.ruc for p in pendientes], password)
    listos = [p for p in pendientes if p.ruc not in problemas]
    excluidos = [Excluido(p.fila, p.id, problemas[p.ruc]) for p in pendientes if p.ruc in problemas]
    for e in excluidos:
        log.warning("Fila %d excluida (id=%s): %s", e.fila, e.id or "-", e.motivo)
    return listos, excluidos
