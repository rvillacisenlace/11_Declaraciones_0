"""Elige de donde salen el Control y las credenciales: Graph (si esta configurado) o el archivo local.

Graph se activa por archivo y de forma explicita: GRAPH_CONTROL_DRIVE_ID + GRAPH_CONTROL_ITEM_ID (Control) y
GRAPH_CREDENCIALES_DRIVE_ID + GRAPH_CREDENCIALES_ITEM_ID (credenciales). Sin esas variables todo sigue siendo local.
Una configuracion a medias es un error: nunca se vuelve en silencio a una copia local que nadie mas ve.
"""
import os

from src.utils.exceptions import ConfigError

_CACHE: dict = {}


def reiniciar() -> None:
    _CACHE.clear()


def _ids(prefijo: str) -> tuple[str, str] | None:
    drive = os.getenv(f"GRAPH_{prefijo}_DRIVE_ID", "").strip()
    item = os.getenv(f"GRAPH_{prefijo}_ITEM_ID", "").strip()
    if not drive and not item:
        return None
    if not (drive and item):
        raise ConfigError(f"Faltan GRAPH_{prefijo}_DRIVE_ID o GRAPH_{prefijo}_ITEM_ID en el .env (deben ir las dos)")
    return drive, item


def cliente_graph():
    from src.microsoft import authentication
    from src.microsoft.graph_client import ClienteGraph

    tenant = os.getenv("MICROSOFT_TENANT_ID", "").strip()
    client = os.getenv("MICROSOFT_CLIENT_ID", "").strip()
    faltan = [n for n, v in (("MICROSOFT_TENANT_ID", tenant), ("MICROSOFT_CLIENT_ID", client)) if not v]
    if faltan:
        raise ConfigError(f"Graph esta activado pero faltan en el .env: {', '.join(faltan)}")
    if _CACHE.get("cliente_de") != (tenant, client):
        _CACHE["cliente"] = ClienteGraph(authentication.AutenticacionGraph(tenant, client, authentication.obtener_secreto()))
        _CACHE["cliente_de"] = (tenant, client)
    return _CACHE["cliente"]


def _archivo(prefijo: str, clase):
    ids = _ids(prefijo)
    if ids is None:
        return None
    clave = (prefijo, *ids)
    if clave not in _CACHE:
        _CACHE[clave] = clase(cliente_graph(), *ids)
    return _CACHE[clave]


def control_graph():
    """ControlGraph si el Control esta en Graph; None si es local. Es siempre el mismo objeto (respalda una sola vez)."""
    if _ids("CONTROL") is None:
        return None
    from src.microsoft.excel_repository import ControlGraph
    return _archivo("CONTROL", ControlGraph)


def credenciales_graph():
    if _ids("CREDENCIALES") is None:
        return None
    from src.microsoft.excel_repository import ArchivoGraph
    return _archivo("CREDENCIALES", ArchivoGraph)
