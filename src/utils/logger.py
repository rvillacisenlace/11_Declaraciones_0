"""Logging con redaccion automatica de secretos en el formateador (cubre tambien los tracebacks)."""
import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler

from config import settings

_PATRONES = (
    (re.compile(r"(?i)\b(password|passwd|clave|secret|api[_-]?key|token|key)\b(\s*[=:]\s*)\S+"), r"\1\2***"),
    (re.compile(r"(https?://[^\s?#;]+)[;?#]\S*"), r"\1"),
    (re.compile(r"[A-Za-z0-9_\-\.]{80,}"), "***TOKEN***"),
)


def redactar(texto: str) -> str:
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto


class _FormatterRedactor(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redactar(super().format(record))


def configurar_logging() -> None:
    raiz = logging.getLogger()
    if raiz.handlers:
        return
    settings.ensure_dirs()
    debug = os.getenv("ZERO_DEBUG") == "1"
    raiz.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = _FormatterRedactor("%(asctime)s %(levelname)s %(name)s: %(message)s")
    archivo = TimedRotatingFileHandler(
        settings.LOGS_DIR / "zero.log", when="midnight",
        backupCount=settings.LOG_RETENTION_DAYS, encoding="utf-8",
    )
    for handler in (archivo, logging.StreamHandler()):
        handler.setFormatter(fmt)
        raiz.addHandler(handler)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    if debug:
        raiz.warning("MODO DEBUG ACTIVO: revisar el log antes de compartirlo")


def get_logger(nombre: str) -> logging.Logger:
    return logging.getLogger(nombre)