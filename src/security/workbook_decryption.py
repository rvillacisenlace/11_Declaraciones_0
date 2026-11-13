"""Descifra el Excel de credenciales EN MEMORIA: nunca se escribe una copia en claro a disco."""
import io

import msoffcrypto

from src.utils.exceptions import ConfigError, ZeroError


def abrir_en_memoria(ruta, password: str) -> io.BytesIO:
    """'ruta' es un archivo local (Path) o un origen remoto con leer_bytes() (Graph): los bytes viven solo en memoria."""
    if not hasattr(ruta, "leer_bytes") and not ruta.is_file():
        raise ConfigError(f"No se encontro el archivo de credenciales: {ruta.name}")
    try:
        if hasattr(ruta, "leer_bytes"):
            contenido = ruta.leer_bytes()
        else:
            with open(ruta, "rb") as f:
                contenido = f.read()
        oficina = msoffcrypto.OfficeFile(io.BytesIO(contenido))
        if not oficina.is_encrypted():
            raise ConfigError("El archivo de credenciales NO esta cifrado: protejalo con contrasena")
        salida = io.BytesIO()
        oficina.load_key(password=password)
        oficina.decrypt(salida)
    except ZeroError:
        raise
    except Exception:
        # No se propaga el detalle: no debe filtrar nada de la ruta ni del contenido.
        raise ConfigError("No se pudo abrir el archivo de credenciales (contrasena incorrecta o archivo danado)") from None
    salida.seek(0)
    return salida
