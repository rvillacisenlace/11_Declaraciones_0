"""Resume el Control SIN mostrar nombres ni RUC: solo conteos, filas y motivos.
Uso:  py -m diagnostics.diag_control "C:/ruta/Control_SRI.xlsx"   (o variable CONTROL_XLSX)"""
import os
import sys
from collections import Counter
from pathlib import Path

from config import settings  # noqa: F401  (carga el .env)
from src.services.fideicomiso_service import leer_control
from src.utils.exceptions import ZeroError
from src.utils.logger import configurar_logging


def main() -> int:
    configurar_logging()
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.getenv("CONTROL_XLSX", "")
    try:
        r = leer_control(Path(ruta) if ruta else None)
    except ZeroError as e:
        print("ERROR:", e)
        return 1
    print(f"\nFilas con datos: {r.total} | omitidas (NO o vacio): {r.omitidos} | "
          f"listas para procesar: {len(r.pendientes)} | excluidas: {len(r.excluidos)}")
    if r.excluidos:
        print("\nExcluidas por motivo:")
        for motivo, n in Counter(m for e in r.excluidos for m in e.motivo.split("; ")).most_common():
            print(f"  {n:4d}  {motivo}")
        print("\nPrimeras filas excluidas:")
        for e in r.excluidos[:15]:
            print(f"  fila {e.fila}: {e.motivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
