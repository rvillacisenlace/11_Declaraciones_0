"""Cliente HTTP de Microsoft Graph: token en cada llamada, tiempos maximos y reintentos ante limites o fallos pasajeros.

Reglas: toda llamada lleva timeout; 429/502/503/504 y los errores de red se reintentan con espera creciente (o la que
indique Retry-After); un 401 renueva el token UNA vez; cualquier otro error se informa sin volcar el cuerpo ni el token.
"""
import time

from src.microsoft.authentication import errores_de_red, usar_almacen_del_sistema
from src.utils.exceptions import ConfigError, GraphError
from src.utils.logger import get_logger

log = get_logger(__name__)
BASE = "https://graph.microsoft.com/v1.0"
REINTENTABLES = {429, 502, 503, 504}


def _nueva_sesion():
    try:
        import requests
    except ImportError:
        raise ConfigError("Falta la libreria requests (pip install requests)") from None
    return requests.Session()


class ClienteGraph:
    def __init__(self, autenticacion, *, sesion=None, dormir=time.sleep, timeout=(10, 60), reintentos: int = 4):
        usar_almacen_del_sistema()
        self._auth = autenticacion
        self._sesion = sesion or _nueva_sesion()
        self._dormir = dormir
        self._timeout = timeout
        self._reintentos = reintentos

    def probar_token(self) -> None:
        self._auth.token()

    def _esperar(self, intento: int, retry_after, motivo: str) -> None:
        try:
            espera = min(60.0, float(retry_after))
        except (TypeError, ValueError):
            espera = float(min(2 ** intento, 30))
        log.warning("Graph: %s; reintento %d de %d en %.0f s", motivo, intento + 1, self._reintentos, espera)
        self._dormir(espera)

    def solicitar(self, metodo: str, ruta: str, *, cuerpo=None, contexto: str = "completar la solicitud",
                  aceptar: str = "application/json"):
        url = ruta if ruta.startswith("http") else BASE + ruta
        intento, renovado = 0, False
        while True:
            try:
                resp = self._sesion.request(
                    metodo, url, headers={"Authorization": f"Bearer {self._auth.token()}", "Accept": aceptar},
                    json=cuerpo, timeout=self._timeout)
            except errores_de_red() as e:
                if intento >= self._reintentos:
                    raise GraphError(f"Graph no responde al intentar {contexto} ({type(e).__name__})") from None
                self._esperar(intento, None, f"error de red ({type(e).__name__})")
                intento += 1
                continue
            if resp.status_code == 401 and not renovado:
                self._auth.renovar()
                renovado = True
                continue
            if resp.status_code in REINTENTABLES and intento < self._reintentos:
                self._esperar(intento, resp.headers.get("Retry-After"), f"HTTP {resp.status_code}")
                intento += 1
                continue
            if resp.status_code >= 400:
                raise GraphError(f"Graph no pudo {contexto}: HTTP {resp.status_code} ({_codigo(resp)})", status=resp.status_code)
            return resp

    def get_json(self, ruta: str, *, contexto: str) -> dict:
        return self.solicitar("GET", ruta, contexto=contexto).json()

    def patch_json(self, ruta: str, cuerpo: dict, *, contexto: str) -> dict:
        return self.solicitar("PATCH", ruta, cuerpo=cuerpo, contexto=contexto).json()

    def descargar(self, ruta: str, *, contexto: str) -> bytes:
        return self.solicitar("GET", ruta, contexto=contexto, aceptar="*/*").content


def _codigo(resp) -> str:
    """Solo el codigo de error de Graph (p. ej. accessDenied); nunca el cuerpo completo."""
    try:
        return str(resp.json().get("error", {}).get("code", "sin codigo"))[:60]
    except Exception:
        return "sin codigo"
