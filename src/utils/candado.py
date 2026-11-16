"""Candado de ejecucion unica: un solo Zero a la vez en el equipo.

Es un bloqueo del sistema operativo sobre un archivo: si el programa se cierra mal o el equipo se apaga, el sistema lo
libera solo (no queda un candado "huerfano" que impida volver a ejecutar). La segunda ejecucion no hace nada.
"""
import sys
from contextlib import contextmanager
from pathlib import Path

from src.utils.exceptions import EjecucionEnCurso

MENSAJE = ("Ya hay otra ejecucion de Zero en curso en este equipo. Espere a que termine; si no ve ninguna ventana, "
           "revise el Administrador de tareas (Zero.exe). No se hizo nada.")


def _tomar(archivo) -> None:
    archivo.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _soltar(archivo) -> None:
    archivo.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)


@contextmanager
def candado_de_ejecucion(ruta: Path):
    """Toma el candado o lanza EjecucionEnCurso. Se libera siempre al salir, incluso con un error."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    archivo = open(ruta, "a+b")
    try:
        _tomar(archivo)
    except OSError:
        archivo.close()
        raise EjecucionEnCurso(MENSAJE) from None
    try:
        yield
    finally:
        try:
            _soltar(archivo)
        finally:
            archivo.close()
