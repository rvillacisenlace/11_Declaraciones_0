"""Cruza Control y Credenciales por RUC SIN mostrar nombres, RUC ni claves: solo conteos y motivos.
Uso:  py -m diagnostics.diag_cruce  (rutas en CONTROL_XLSX y CREDENCIALES_XLSX del .env)"""
import getpass
import sys
from collections import Counter

from config import settings
from src.services.fideicomiso_service import cruzar_credenciales, leer_control, ruta_control
from src.utils.exceptions import ZeroError
from src.utils.logger import configurar_logging


def main() -> int:
    configurar_logging()
    try:
        r = leer_control(ruta_control())
        listos, extra = cruzar_credenciales(r.pendientes, getpass.getpass("Contrasena del archivo de credenciales: "))
    except ZeroError as e:
        print("ERROR:", e)
        return 1
    excluidos = r.excluidos + extra
    print(f"\nControl: {r.total} filas | omitidas (NO o vacio): {r.omitidos} | marcadas SI: {len(r.pendientes) + len(r.excluidos)}")
    print(f"Listas para procesar: {len(listos)} | excluidas: {len(excluidos)}")
    for motivo, n in Counter(m for e in excluidos for m in e.motivo.split("; ")).most_common():
        print(f"  {n:4d}  {motivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
