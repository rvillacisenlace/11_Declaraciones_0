"""Describe la ESTRUCTURA del Excel cifrado de credenciales sin mostrar valores:
hojas, encabezados, filas llenas por columna y, solo para columnas de tipo/rol, cuantas filas hay por categoria.
Uso:  py -m diagnostics.diag_credenciales "D:/ruta/Credenciales_SRI.xlsx"   (o variable CREDENCIALES_XLSX)"""
import getpass
import os
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from config import settings  # noqa: F401  (carga el .env)
from src.security.workbook_decryption import abrir_en_memoria
from src.utils.exceptions import ZeroError
from src.utils.validators import enmascarar_digitos


def _norm(t) -> str:
    return str(t or "").strip().lower()


def main() -> int:
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CREDENCIALES_XLSX", "")
    if not ruta:
        print("ERROR: indique la ruta del archivo o defina CREDENCIALES_XLSX")
        return 1
    try:
        libro = load_workbook(abrir_en_memoria(Path(ruta), getpass.getpass("Contrasena del archivo: ")),
                              read_only=True, data_only=True)
    except ZeroError as e:
        print("ERROR:", e)
        return 1
    try:
        for ws in libro.worksheets:
            filas = list(ws.iter_rows(values_only=True))
            print(f"\nHoja {enmascarar_digitos(ws.title)!r} ({ws.sheet_state}): {max(len(filas) - 1, 0)} filas de datos")
            if not filas:
                continue
            enc, datos = filas[0], filas[1:]
            for j, nombre in enumerate(enc):
                col = [str(f[j]).strip() for f in datos if j < len(f) and f[j] not in (None, "")]
                extra = ""
                if _norm(nombre) in ("tipo", "rol", "perfil") and len(set(col)) <= 6:
                    extra = " | " + ", ".join(f"{k}={v}" for k, v in Counter(col).most_common())
                elif _norm(nombre) == "id":
                    extra = f" | ids repetidos: {sum(1 for c in Counter(col).values() if c > 1)}"
                print(f"  [{j}] {enmascarar_digitos(str(nombre or ''))!r}: llenas={len(col)}/{len(datos)}{extra}")
    finally:
        libro.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
