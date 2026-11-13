"""Diagnostico de Microsoft Graph. NO escribe nada en el Control ni en OneDrive y nunca muestra nombres, RUC, claves ni tokens.

  py -m diagnostics.diag_graph
      Comprueba la configuracion, donde esta el secreto, que el token se obtiene y que los archivos se leen.
  py -m diagnostics.diag_graph --buscar CUENTA RUTA --como control|credenciales [--escribir]
      Localiza el drive_id y el item_id de un archivo de OneDrive; con --escribir los guarda en el .env.
"""
import argparse
import io
from urllib.parse import quote

import msoffcrypto
from dotenv import set_key

from config import settings
from src.microsoft import authentication, fuentes
from src.services.fideicomiso_service import MARCAS, leer_control
from src.utils.exceptions import ZeroError


def _estado(ok: bool, texto: str) -> None:
    print(f"  [{'OK' if ok else 'FALLA'}] {texto}")


def buscar(cliente, cuenta: str, ruta: str) -> tuple[str, str]:
    """drive_id e item_id de un archivo de la cuenta de OneDrive (mismos endpoints que ya funcionan en ACW)."""
    usuario = quote(cuenta, safe="@")
    drive = cliente.get_json(f"/users/{usuario}/drive", contexto="obtener el drive de la cuenta")["id"]
    item = cliente.get_json(f"/users/{usuario}/drive/root:/{quote(ruta.strip('/'), safe='/')}",
                            contexto="encontrar el archivo en esa ruta")["id"]
    return drive, item


def _activo(prefijo: str) -> bool:
    try:
        return fuentes._ids(prefijo) is not None
    except ZeroError as e:
        _estado(False, str(e))
        return False


def verificar() -> int:
    control, credenciales = _activo("CONTROL"), _activo("CREDENCIALES")
    print("Origen de los datos:")
    print(f"  Control:       {'Graph' if control else 'archivo local (CONTROL_XLSX)'}")
    print(f"  Credenciales:  {'Graph' if credenciales else 'archivo local (CREDENCIALES_XLSX)'}")
    if not (control or credenciales):
        print("Graph no esta activado: no hay nada que comprobar.")
        return 0
    fallas = 0

    def paso(titulo, accion):
        nonlocal fallas
        try:
            _estado(True, accion())
        except ZeroError as e:
            fallas += 1
            _estado(False, f"{titulo}: {e}")
            return False
        return True

    print("Comprobaciones:")
    origen = authentication.origen_del_secreto()
    _estado(origen is not None, f"secreto de Microsoft: {origen or 'NO ENCONTRADO'}")
    fallas += origen is None
    if origen is None or not paso("token", lambda: (fuentes.cliente_graph().probar_token(), "token de Graph obtenido")[1]):
        return 1
    if control:
        def leer_el_control():
            archivo = fuentes.control_graph()
            partes = []
            for marca in MARCAS:
                r = leer_control(archivo, marca)
                partes.append(f"{marca}: {r.total} filas, {r.omitidos} omitidas, {len(r.pendientes)} pendientes, "
                              f"{len(r.excluidos)} excluidas")
            return "Control leido (" + " | ".join(partes) + ")"
        paso("Control", leer_el_control)
    if credenciales:
        def leer_credenciales():
            datos = fuentes.credenciales_graph().leer_bytes()
            try:
                cifrado = msoffcrypto.OfficeFile(io.BytesIO(datos)).is_encrypted()
            except Exception:
                raise ZeroError("el archivo descargado no es un libro de Excel valido") from None
            if not cifrado:
                raise ZeroError("el archivo de credenciales NO esta cifrado")
            return f"credenciales descargadas ({len(datos)} bytes, cifradas; no se descifran aqui)"
        paso("Credenciales", leer_credenciales)
    print("RESULTADO:", "todo correcto" if not fallas else f"{fallas} comprobacion(es) fallaron")
    return 1 if fallas else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="diag_graph")
    ap.add_argument("--buscar", nargs=2, metavar=("CUENTA", "RUTA"), help="cuenta de OneDrive y ruta del archivo")
    ap.add_argument("--como", choices=("control", "credenciales"), help="a que variable corresponde el archivo (con --escribir)")
    ap.add_argument("--escribir", action="store_true", help="guarda drive_id e item_id en el .env")
    args = ap.parse_args(argv)
    if args.escribir and not (args.buscar and args.como):
        ap.error("--escribir necesita --buscar y --como")
    if not args.buscar:
        return verificar()
    try:
        drive, item = buscar(fuentes.cliente_graph(), *args.buscar)
    except ZeroError as e:
        print(f"ERROR: {e}")
        return 1
    prefijo = (args.como or "CONTROL").upper()
    print(f"GRAPH_{prefijo}_DRIVE_ID={drive}\nGRAPH_{prefijo}_ITEM_ID={item}")
    if args.escribir:
        entorno = str(settings.HOME / ".env")
        set_key(entorno, f"GRAPH_{prefijo}_DRIVE_ID", drive)
        set_key(entorno, f"GRAPH_{prefijo}_ITEM_ID", item)
        print(f"Guardado en {entorno}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
