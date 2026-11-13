"""Marca 'DECLARADO' en UNA celda del Control sin tocar nada mas del archivo.
No se regraba el libro con una libreria (deformaria tablas, estilos y validaciones): se edita SOLO el elemento de esa
celda dentro de su hoja. Candados: la fila debe traer el ID esperado, la celda debe decir SI (nunca se pisa otro valor ni
una formula), se hace una copia de seguridad, el resultado se verifica celda por celda y el archivo se reemplaza de forma
atomica. Si el Control esta abierto en Excel no se puede reemplazar: se avisa y se marca a mano."""
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from config import settings
from src.services.fideicomiso_service import HOJA, MARCAS, _norm
from src.utils.exceptions import ConfigError
from src.utils.logger import get_logger

log = get_logger(__name__)
TEXTO = "DECLARADO"
_RESPALDADOS: set = set()  # una copia de seguridad por archivo y por ejecucion


def _valores(ruta: Path) -> dict:
    libro = load_workbook(ruta, read_only=True, data_only=False)
    try:
        return {h: [tuple(f) for f in libro[h].iter_rows(values_only=True)] for h in libro.sheetnames}
    finally:
        libro.close()


def _hoja_xml(zf: zipfile.ZipFile) -> str:
    wb = zf.read("xl/workbook.xml").decode("utf-8")
    m = re.search(r'<sheet\b[^>]*\bname="%s"[^>]*\br:id="([^"]+)"' % re.escape(HOJA), wb)
    if not m:
        raise ConfigError(f"Falta la hoja '{HOJA}' en el archivo de control")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    for rel in re.findall(r"<Relationship\b[^>]*>", rels):
        if f'Id="{m.group(1)}"' in rel:
            destino = re.search(r'Target="([^"]+)"', rel).group(1)
            return destino.lstrip("/") if destino.startswith("/") else "xl/" + destino
    raise ConfigError("No se encontro la hoja de fideicomisos dentro del archivo de control")


def _parchear(xml: str, celda: str) -> str:
    patron = re.compile(r'<c r="%s"(?P<attrs>[^>]*?)(?:/>|>(?P<inner>.*?)</c>)' % celda, re.S)
    coincidencias = patron.findall(xml)
    if len(coincidencias) != 1:
        raise ConfigError(f"No se pudo ubicar la celda {celda} en el archivo de control")
    attrs, inner = coincidencias[0]
    if "<f" in (inner or ""):
        raise ConfigError(f"La celda {celda} es una formula: no se modifica")
    attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
    nueva = f'<c r="{celda}"{attrs} t="inlineStr"><is><t>{TEXTO}</t></is></c>'
    return patron.sub(lambda _: nueva, xml, count=1)


def _verificar(antes: dict, despues: dict, fila: int, col: int) -> None:
    esperado = {h: [list(f) for f in filas] for h, filas in antes.items()}
    esperado[HOJA][fila - 1][col] = TEXTO
    if {h: [list(f) for f in filas] for h, filas in despues.items()} != esperado:
        raise ConfigError("La verificacion del Control marcado no coincide con lo esperado: no se reemplaza el archivo")


def marcar_declarado(ruta, fila: int, id_: str, marca: str, respaldos: Path | None = None) -> bool:
    """Pone DECLARADO en la celda de 'marca' de esa fila. True si la celda queda en DECLARADO; False si no se tocó
    (el ID no coincide o la celda ya no dice SI)."""
    if hasattr(ruta, "marcar_declarado"):  # origen remoto (Graph): lo anota su propio repositorio
        return ruta.marcar_declarado(fila, id_, marca, respaldos)
    if marca not in MARCAS:
        raise ConfigError(f"Marca desconocida: {marca}")
    if ruta is None or not Path(ruta).is_file():
        raise ConfigError("No se encontro el archivo de control")
    ruta = Path(ruta)
    antes = _valores(ruta)
    filas = antes.get(HOJA)
    if not filas:
        raise ConfigError(f"Falta la hoja '{HOJA}' en el archivo de control")
    encabezado = [_norm(c) for c in filas[0]]
    if "id" not in encabezado or marca not in encabezado:
        raise ConfigError(f"Faltan columnas en '{HOJA}'")
    c_id, c_marca = encabezado.index("id"), encabezado.index(marca)
    if not 2 <= fila <= len(filas):
        log.warning("Control: la fila %s no existe; no se marca %s", fila, id_)
        return False
    registro = filas[fila - 1]
    if str(registro[c_id] or "").strip() != str(id_):
        log.warning("Control: la fila %s ya no es el ID %s; no se marca", fila, id_)
        return False
    valor = _norm(registro[c_marca])
    if valor == "declarado":
        return True
    if valor != "si":
        log.warning("Control: la celda de %s ya no dice SI; no se modifica", id_)
        return False

    if ruta.resolve() not in _RESPALDADOS:
        carpeta = Path(respaldos) if respaldos else settings.DATA_DIR / "respaldos"
        carpeta.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ruta, carpeta / f"{ruta.stem}.respaldo_{datetime.now():%Y%m%d_%H%M%S}{ruta.suffix}")
        _RESPALDADOS.add(ruta.resolve())

    celda = f"{get_column_letter(c_marca + 1)}{fila}"
    fd, tmp_nombre = tempfile.mkstemp(prefix="~zero_", suffix=".xlsx", dir=ruta.parent)  # misma carpeta: reemplazo atomico
    os.close(fd)
    tmp = Path(tmp_nombre)
    try:
        with zipfile.ZipFile(ruta) as origen, zipfile.ZipFile(tmp, "w") as destino:
            hoja = _hoja_xml(origen)
            for info in origen.infolist():
                datos = origen.read(info.filename)
                if info.filename == hoja:
                    datos = _parchear(datos.decode("utf-8"), celda).encode("utf-8")
                destino.writestr(info, datos, compress_type=info.compress_type)
        load_workbook(tmp).close()  # el XML resultante debe ser valido
        _verificar(antes, _valores(tmp), fila, c_marca)
        try:
            os.replace(tmp, ruta)
        except PermissionError:
            raise ConfigError("El Control esta abierto en otro programa (Excel): cierrelo para que se pueda marcar") from None
    finally:
        tmp.unlink(missing_ok=True)
    log.info("Control: %s de %s marcado como %s", marca.upper(), id_, TEXTO)
    return True