"""Descifra el Excel de credenciales EN MEMORIA: nunca se escribe una copia en claro a disco."""
import io
from pathlib import Path

import msoffcrypto

from src.utils.exceptions import ConfigError


def abrir_en_memoria(ruta: Path, password: str) -> io.BytesIO:
    if not ruta.is_file():
        raise ConfigError(f"No se encontro el archivo de credenciales: {ruta.name}")
    try:
        with open(ruta, "rb") as f:
            oficina = msoffcrypto.OfficeFile(f)
            if not oficina.is_encrypted():
                raise ConfigError("El archivo de credenciales NO esta cifrado: protejalo con contrasena")
            salida = io.BytesIO()
            oficina.load_key(password=password)
            oficina.decrypt(salida)
    except ConfigError:
        raise
    except Exception:
        # No se propaga el detalle: no debe filtrar nada de la ruta ni del contenido.
        raise ConfigError("No se pudo abrir el archivo de credenciales (contrasena incorrecta o archivo danado)") from None
    salida.seek(0)
    return salida
