"""Reorganiza lo ya guardado al arbol definitivo, usando el Control para saber el responsable de cada RUC:
    Declaraciones/<Responsable>/<RUC>/<codigo - impuesto>/<serie>_<ruc>_<fecha>.pdf
    Evidencias/<Responsable>/<RUC>/<AAAA-MM>_<nombre original>.png              (con --capturas)
Por defecto SOLO SIMULA. Con --aplicar mueve (nunca borra ni sobrescribe; solo quita carpetas que quedaron vacias).
Busca en la carpeta antigua (--origen) y en lo que ya hay en Declaraciones y Evidencias. Lo que no se pueda ubicar con
certeza (RUC o ID que no estan en el Control, o que aparecen repetidos con datos distintos) se deja donde esta y se
informa. Se puede repetir sin problema.  Uso:  py -m diagnostics.mover_comprobantes [--aplicar] [--capturas]"""
import argparse
import re
import shutil
import sys
from pathlib import Path

from config import settings
from src.services.fideicomiso_service import leer_directorio, ruta_control
from src.sri import verification
from src.utils.exceptions import ZeroError
from src.utils.logger import configurar_logging
from src.utils.rutas import carpeta_declaracion, carpeta_evidencia
from src.utils.validators import enmascarar_ruc

PATRON = re.compile(r"^\d{8,}_\d{13}_\d{14}\.pdf$")  # serie_ruc_AAAAMMDDHHMMSS.pdf (no toca los RECHAZADO_*)
PERIODO = re.compile(r"^\d{4}-\d{2}$")


def _raices(*candidatas: Path) -> list[Path]:
    vistas, raices = set(), []
    for r in candidatas:
        if r.is_dir() and r.resolve() not in vistas:
            vistas.add(r.resolve())
            raices.append(r)
    return raices


def _limpiar_vacias(carpeta: Path, raiz: Path) -> None:
    """Quita las carpetas que quedaron vacias al mover, sin salirse de la raiz ni tocar la raiz misma."""
    raiz = raiz.resolve()
    carpeta = carpeta.resolve()
    while carpeta != raiz and raiz in carpeta.parents:
        try:
            carpeta.rmdir()
        except OSError:
            break
        carpeta = carpeta.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mover_comprobantes")
    ap.add_argument("--origen", default=str(settings.HOME / "evidence"), help="carpeta antigua donde estan hoy")
    ap.add_argument("--aplicar", action="store_true", help="mueve de verdad (sin esto solo simula)")
    ap.add_argument("--capturas", action="store_true", help="mueve tambien las capturas .png a Evidencias/<Responsable>/<RUC>")
    args = ap.parse_args(argv)
    configurar_logging()
    origen = Path(args.origen)
    if not origen.is_dir():
        print(f"ERROR: no existe la carpeta de origen: {origen}")
        return 1
    try:
        directorio = leer_directorio(ruta_control())
    except ZeroError as e:
        print(f"ERROR: no se pudo leer el Control para saber los responsables: {e}")
        return 1
    modo = "MOVIENDO" if args.aplicar else "SIMULACION (no se mueve nada; use --aplicar)"
    print(f"{modo}\norigen: {origen}\n")
    if directorio.ambiguos:
        print(f"  AVISO: {len(directorio.ambiguos)} ID o RUC aparecen repetidos con datos distintos en el Control; "
              "esos no se mueven.")

    movidos = saltados = ilegibles = sin_ubicar = 0
    for raiz in _raices(origen, settings.DECLARACIONES_DIR):
        for pdf in sorted(raiz.rglob("*.pdf")):
            if not PATRON.match(pdf.name):
                continue
            try:
                c = verification.leer_pdf(pdf)
                codigo = c.impuesto.split()[0]
                if c.ruc not in directorio.por_ruc:
                    print(f"  SIN RESPONSABLE EN EL CONTROL, se deja: serie {c.serie} | RUC {enmascarar_ruc(c.ruc)}")
                    sin_ubicar += 1
                    continue
                destino = carpeta_declaracion(directorio.por_ruc[c.ruc], c.ruc, codigo)
            except ZeroError as e:
                print(f"  NO SE PUDO LEER {pdf.name}: {e}")
                ilegibles += 1
                continue
            final = destino / pdf.name
            if pdf.resolve() == final.resolve():
                continue
            if final.exists():
                print(f"  YA EXISTE en el destino, se deja: serie {c.serie}")
                saltados += 1
                continue
            print(f"  serie {c.serie} | RUC {enmascarar_ruc(c.ruc)} -> {destino.parent.parent.name}\\{destino.parent.name[:4]}***\\{destino.name}")
            if args.aplicar:
                destino.mkdir(parents=True, exist_ok=True)
                shutil.move(str(pdf), str(final))
                _limpiar_vacias(pdf.parent, raiz)
            movidos += 1

    capturas = capturas_sin_ubicar = 0
    if args.capturas:
        for raiz in _raices(origen, settings.EVIDENCE_DIR):
            for png in sorted(raiz.rglob("*.png")):
                partes = png.relative_to(raiz).parts
                if len(partes) != 3 or not PERIODO.match(partes[1]):
                    continue  # solo el esquema antiguo: <ID>/<AAAA-MM>/<archivo>.png
                if partes[0] not in directorio.por_id:
                    capturas_sin_ubicar += 1
                    continue
                ruc, responsable = directorio.por_id[partes[0]]
                final = carpeta_evidencia(responsable, ruc) / f"{partes[1]}_{png.name}"
                if final.exists():
                    continue
                if args.aplicar:
                    final.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(png), str(final))
                    _limpiar_vacias(png.parent, raiz)
                capturas += 1
        if capturas_sin_ubicar:
            print(f"  {capturas_sin_ubicar} captura(s) de IDs que no estan en el Control: se dejan donde estan.")
    print(f"\n{'Movidos' if args.aplicar else 'Se moverian'}: {movidos} comprobante(s) | ya existian: {saltados} | "
          f"ilegibles: {ilegibles} | sin responsable: {sin_ubicar} | capturas: {capturas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())