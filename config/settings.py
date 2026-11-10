"""Configuracion y rutas. Todo vive en %APPDATA%\\Zero (o ZERO_HOME, para desarrollo)."""
import os
from pathlib import Path

from dotenv import load_dotenv

VERSION = "0.1.0"

HOME = Path(os.getenv("ZERO_HOME") or Path(os.getenv("APPDATA", "")) / "Zero")
load_dotenv(HOME / ".env")

AUTH_DIR = HOME / ".auth"
LOGS_DIR = HOME / "logs"
DATA_DIR = HOME / "data"
# Carpeta visible para el usuario (p. ej. D:/Documentos/Zero): Declaraciones/<RUC>/<impuesto>/ y Evidencias/.
# Sin ZERO_DOCS todo queda dentro de HOME, como antes.
_DOCS = os.getenv("ZERO_DOCS")
DECLARACIONES_DIR = Path(_DOCS) / "Declaraciones" if _DOCS else HOME / "declaraciones"
EVIDENCE_DIR = Path(_DOCS) / "Evidencias" if _DOCS else HOME / "evidence"

def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    return defecto if valor is None else valor.strip().lower() in ("1", "true", "si", "yes")


DRY_RUN = _bool("DRY_RUN", True)  # por defecto NO se envia nada
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "30000"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
SRI_LOGIN_URL = os.getenv("SRI_LOGIN_URL", "")
FORM_IVA_URL = os.getenv("FORM_IVA_URL", "")
CREDENCIALES_XLSX = Path(os.getenv("CREDENCIALES_XLSX", "")) if os.getenv("CREDENCIALES_XLSX") else None

def ensure_dirs() -> None:
    for d in (AUTH_DIR, LOGS_DIR, DATA_DIR, EVIDENCE_DIR, DECLARACIONES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def validar() -> None:
    from src.utils.exceptions import ConfigError

    faltan = [n for n, v in (("SRI_LOGIN_URL", SRI_LOGIN_URL),) if not v]
    if faltan:
        raise ConfigError(f"Faltan variables en {HOME / '.env'}: {', '.join(faltan)}")
