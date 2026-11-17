"""Datos de la cabecera de la ventana: periodo y cuantos fideicomisos hay marcados SI. Sin tkinter."""
from dataclasses import dataclass

from src.utils.exceptions import ZeroError
from src.utils.validators import periodo_a_declarar


@dataclass
class Resumen:
    periodo: str
    iva: int | None = None
    retenciones: int | None = None
    origen: str = ""
    error: str | None = None


def calcular_resumen() -> Resumen:
    anio, mes = periodo_a_declarar()
    periodo = f"{mes:02d}-{anio}"
    try:
        import main
        from src.services.fideicomiso_service import leer_control, ruta_control
        ruta = ruta_control()
        iva = len(leer_control(ruta, main._marca("2011")).pendientes)
        ret = len(leer_control(ruta, main._marca("1031")).pendientes)
        return Resumen(periodo, iva, ret, "OneDrive" if hasattr(ruta, "leer_filas") else "Archivo local")
    except ZeroError as e:
        return Resumen(periodo, error=str(e)[:200])
    except Exception as e:
        return Resumen(periodo, error=f"{type(e).__name__}: no se pudo leer el Control")
