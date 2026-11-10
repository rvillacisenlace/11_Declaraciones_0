"""Mueve los comprobantes ya descargados al arbol definitivo:
    <Declaraciones>/<RUC>/<codigo - impuesto>/<serie>_<ruc>_<fecha>.pdf
Por defecto SOLO SIMULA. Con --aplicar mueve (nunca borra ni sobrescribe). Con --capturas mueve tambien las
capturas (.png) a la carpeta de Evidencias. Uso:  py -m diagnostics.mover_comprobantes [--aplicar] [--capturas]"""
import argparse
import re
import shutil
import sys
from pathlib import Path

from config import settings
from src.sri import verification
from src.utils.exceptions import ZeroError
from src.utils.logger import configurar_logging
from src.utils.rutas import carpeta_declaracion
from src.utils.validators import enmascarar_ruc

PATRON = re.compile(r"^\d{8,}_\d{13}_\d{14}\.pdf$")  # serie_ruc_AAAAMMDDHHMMSS.pdf (no toca los RECHAZADO_*)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mover_comprobantes")
    ap.add_argument("--origen", default=str(settings.HOME / "evidence"), help="carpeta donde estan hoy")
    ap.add_argument("--aplicar", action="store_true", help="mueve de verdad (sin esto solo simula)")
    ap.add_argument("--capturas", action="store_true", help="mueve tambien las capturas .png a Evidencias")
    args = ap.parse_args(argv)
    configurar_logging()
    origen = Path(args.origen)
    if not origen.is_dir():
        print(f"ERROR: no existe la carpeta de origen: {origen}")
        return 1
    modo = "MOVIENDO" if args.aplicar else "SIMULACION (no se mueve nada; use --aplicar)"
    print(f"{modo}\norigen: {origen}\n")
    movidos = saltados = ilegibles = 0
    for pdf in sorted(origen.rglob("*.pdf")):
        if not PATRON.match(pdf.name):
            continue
        try:
            c = verification.leer_pdf(pdf)
            destino = carpeta_declaracion(c.ruc, c.impuesto.split()[0])
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
        print(f"  serie {c.serie} | RUC {enmascarar_ruc(c.ruc)} -> {destino.parent.name[:4]}***\\{destino.name}")
        if args.aplicar:
            destino.mkdir(parents=True, exist_ok=True)
            shutil.move(str(pdf), str(final))
        movidos += 1
    capturas = 0
    if args.capturas:
        if origen.resolve() == settings.EVIDENCE_DIR.resolve():
            print("\nLas capturas ya estan en la carpeta de Evidencias: nada que mover.")
        else:
            for png in sorted(origen.rglob("*.png")):
                final = settings.EVIDENCE_DIR / png.relative_to(origen)
                if final.exists():
                    continue
                if args.aplicar:
                    final.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(png), str(final))
                capturas += 1
    print(f"\n{'Movidos' if args.aplicar else 'Se moverian'}: {movidos} comprobante(s) | ya existian: {saltados} | "
          f"ilegibles: {ilegibles} | capturas: {capturas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())