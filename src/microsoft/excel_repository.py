"""El Control y el archivo de credenciales cuando viven en OneDrive/SharePoint (Microsoft Graph).

- ControlGraph: lee la hoja con la API de workbook y anota DECLARADO en UNA celda (no toca nada mas del libro).
- ArchivoGraph: descarga los bytes (el archivo de credenciales va cifrado: se descifra en memoria, igual que en local).
"""
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from openpyxl.utils import column_index_from_string, get_column_letter

from config import settings
from src.services.control_writer import TEXTO
from src.services.fideicomiso_service import HOJA, MARCAS, _norm
from src.utils.exceptions import ConfigError, GraphError
from src.utils.logger import get_logger

log = get_logger(__name__)
_ORIGEN = re.compile(r"!\$?([A-Z]{1,3})\$?(\d+)")


class _ItemGraph:
    def __init__(self, cliente, drive_id: str, item_id: str):
        self._cliente = cliente
        self._item = f"/drives/{drive_id}/items/{item_id}"

    def leer_bytes(self) -> bytes:
        return self._cliente.descargar(f"{self._item}/content", contexto="descargar el archivo")


class ArchivoGraph(_ItemGraph):
    """Archivo binario (credenciales cifradas): solo se descarga a memoria."""


class ControlGraph(_ItemGraph):
    def __init__(self, cliente, drive_id: str, item_id: str):
        super().__init__(cliente, drive_id, item_id)
        self._hoja = f"{self._item}/workbook/worksheets/{quote(HOJA, safe='')}"
        self._respaldado = False

    def leer_filas(self) -> list[tuple]:
        """Filas de la hoja tal como las daria un lector local: desde la fila 1 y la columna A (la primera es el encabezado)."""
        datos = self._cliente.get_json(f"{self._hoja}/usedRange", contexto="leer el Control")
        m = _ORIGEN.search(str(datos.get("address", "")))
        if not m:
            raise GraphError("Graph devolvio un rango del Control que no se puede interpretar")
        col0, fila0 = column_index_from_string(m.group(1)), int(m.group(2))
        relleno = (None,) * (col0 - 1)
        return [()] * (fila0 - 1) + [relleno + tuple(f) for f in datos.get("values") or []]

    def _respaldar(self, respaldos) -> None:
        if self._respaldado:
            return
        carpeta = Path(respaldos) if respaldos else settings.DATA_DIR / "respaldos"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"Control_Graph.respaldo_{datetime.now():%Y%m%d_%H%M%S}.xlsx").write_bytes(self.leer_bytes())
        self._respaldado = True

    def marcar_declarado(self, fila: int, id_: str, marca: str, respaldos=None) -> bool:
        """Mismas reglas que el Control local: solo si la fila sigue siendo ese ID y la celda dice SI. True si queda DECLARADO."""
        if marca not in MARCAS:
            raise ConfigError(f"Marca desconocida: {marca}")
        filas = self.leer_filas()
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
        if str(registro[c_id] if c_id < len(registro) else "").strip() != str(id_):
            log.warning("Control: la fila %s ya no es el ID %s; no se marca", fila, id_)
            return False
        valor = _norm(registro[c_marca] if c_marca < len(registro) else "")
        if valor == "declarado":
            return True
        if valor != "si":
            log.warning("Control: la celda de %s ya no dice SI; no se modifica", id_)
            return False

        self._respaldar(respaldos)  # sin copia de seguridad no se marca
        celda = f"{get_column_letter(c_marca + 1)}{fila}"
        rango = f"{self._hoja}/range(address='{celda}')"
        self._cliente.patch_json(rango, {"values": [[TEXTO]]}, contexto="anotar DECLARADO en el Control")
        leido = self._cliente.get_json(rango, contexto="verificar la anotacion en el Control").get("values", [[None]])[0][0]
        if _norm(leido) != "declarado":
            raise ConfigError("Graph no confirmo la anotacion en el Control: revise la celda a mano")
        log.info("Control: %s de %s marcado como %s", marca.upper(), id_, TEXTO)
        return True
