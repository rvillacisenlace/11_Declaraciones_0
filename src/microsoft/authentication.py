"""Autenticacion con Microsoft Graph (cliente confidencial, credenciales de aplicacion) y custodia del secreto.

El secreto NUNCA viaja en el .exe ni se escribe en el log. Se busca, en este orden:
  1. Administrador de credenciales de Windows, bajo el nombre indicado en MICROSOFT_SECRET_TARGET.
  2. MICROSOFT_CLIENT_SECRET en el .env (texto plano: solo como ultimo recurso; se avisa en el log).
"""
import os
import sys

from src.utils.exceptions import ConfigError, GraphError
from src.utils.logger import get_logger

log = get_logger(__name__)
ALCANCE = ["https://graph.microsoft.com/.default"]
_AVISO = {"texto_plano": False}
_TLS = {"listo": False}


def usar_almacen_del_sistema() -> None:
    """Con inspeccion TLS en la red corporativa hay que confiar en el almacen de certificados de Windows.
    Debe ejecutarse ANTES de la primera conexion: MSAL ya consulta la red al crear la aplicacion."""
    if _TLS["listo"]:
        return
    _TLS["listo"] = True
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:  # sin truststore se usa la configuracion normal de requests
        log.debug("truststore no disponible")


def errores_de_red() -> tuple:
    try:
        import requests
        return (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    except ImportError:
        return ()


class AutenticacionGraph:
    """Pide tokens a MSAL, que los guarda en cache y solo consulta la red cuando el token esta por vencer."""

    def __init__(self, tenant_id: str, client_id: str, secreto: str, *, crear_app=None):
        self._datos = (tenant_id, client_id, secreto)
        self._crear_app = crear_app or self._app_msal
        self._app = self._crear_app(tenant_id, client_id, secreto)

    @staticmethod
    def _app_msal(tenant_id: str, client_id: str, secreto: str):
        usar_almacen_del_sistema()
        try:
            import msal
        except ImportError:
            raise ConfigError("Falta la libreria msal (pip install msal)") from None
        try:  # MSAL consulta la red al crearse (descubre la autoridad): sin red o con un tenant mal escrito falla aqui
            return msal.ConfidentialClientApplication(
                client_id=client_id,
                authority=f"https://login.microsoftonline.com/{tenant_id}",
                client_credential=secreto,
                timeout=30,
            )
        except Exception as e:
            raise GraphError(f"No se pudo iniciar la autenticacion con Microsoft ({type(e).__name__}): "
                             "revise la conexion y MICROSOFT_TENANT_ID") from None

    def token(self) -> str:
        try:
            resultado = self._app.acquire_token_for_client(scopes=ALCANCE)
        except errores_de_red():
            raise  # el cliente HTTP los reintenta
        except Exception as e:
            raise GraphError(f"No se pudo obtener el token de Graph ({type(e).__name__})") from None
        if "access_token" not in resultado:
            detalle = str(resultado.get("error_description", ""))[:200].replace(self._datos[2], "***")
            raise GraphError(f"No se pudo obtener el token de Graph: {resultado.get('error', 'error desconocido')}: {detalle}")
        return resultado["access_token"]

    def renovar(self) -> None:
        """Descarta el cache de MSAL (por ejemplo tras un 401) para forzar un token nuevo."""
        self._app = self._crear_app(*self._datos)


def _decodificar_blob(blob: bytes) -> str | None:
    """Los secretos guardados con cmdkey son UTF-16 (con ceros intercalados); si no hay ceros, se lee como UTF-8."""
    if not blob:
        return None
    try:
        if b"\x00" in blob:
            texto = blob.decode("utf-16-le").rstrip("\x00")
        else:
            texto = blob.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return texto if texto and texto.isprintable() else None


def leer_credencial_windows(destino: str) -> str | None:
    """Lee una credencial generica del Administrador de credenciales de Windows. En otros sistemas devuelve None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENCIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    leer = advapi.CredReadW
    leer.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENCIAL))]
    leer.restype = wintypes.BOOL
    liberar = advapi.CredFree
    liberar.argtypes = [ctypes.c_void_p]
    liberar.restype = None
    puntero = ctypes.POINTER(CREDENCIAL)()
    if not leer(destino, 1, 0, ctypes.byref(puntero)):  # 1 = CRED_TYPE_GENERIC
        return None
    try:
        c = puntero.contents
        blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
    finally:
        liberar(puntero)
    return _decodificar_blob(blob)


def _buscar_secreto() -> tuple[str, str] | None:
    destino = os.getenv("MICROSOFT_SECRET_TARGET", "").strip()
    if destino:
        valor = leer_credencial_windows(destino)
        if valor:
            return valor, "Administrador de credenciales"
        log.warning("No se encontro la credencial '%s' en el Administrador de credenciales", destino)
    valor = os.getenv("MICROSOFT_CLIENT_SECRET", "").strip()
    if valor:
        return valor, ".env (texto plano)"
    return None


def obtener_secreto() -> str:
    hallado = _buscar_secreto()
    if hallado is None:
        raise ConfigError("Falta el secreto de Microsoft: guardelo en el Administrador de credenciales y ponga su nombre "
                          "en MICROSOFT_SECRET_TARGET (o, como ultimo recurso, MICROSOFT_CLIENT_SECRET en el .env)")
    valor, origen = hallado
    if origen.startswith(".env") and not _AVISO["texto_plano"]:
        _AVISO["texto_plano"] = True
        log.warning("El secreto de Microsoft esta en el .env en texto plano: pase a MICROSOFT_SECRET_TARGET")
    return valor


def origen_del_secreto() -> str | None:
    """Donde se encontro el secreto (sin leerlo en pantalla); None si no esta. Sirve para los diagnosticos."""
    hallado = _buscar_secreto()
    return hallado[1] if hallado else None
