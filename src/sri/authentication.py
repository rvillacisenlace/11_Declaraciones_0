"""Login automatico con las credenciales del Excel. UN SOLO INTENTO: ante la duda se detiene."""
from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PWTimeout

from src.security.credential_repository import Credencial
from src.sri import selectors as sel
from src.utils.exceptions import CredentialsRejected, LoginError
from src.utils.logger import get_logger
from src.utils.validators import url_corta

log = get_logger(__name__)

ESTABLE_S = 8  # la sesion debe aguantar este tiempo fuera del login


def _escribir(page: Page, selector: str, texto: str, etiqueta: str) -> None:
    campo = page.locator(selector)
    campo.click()
    campo.fill("")
    campo.press_sequentially(texto, delay=40)  # los campos bloquean pegar
    if len(campo.input_value()) != len(texto):
        raise LoginError(f"El campo {etiqueta} no recibio todo el texto")


def iniciar_sesion(context: BrowserContext, page: Page, login_url: str, cred: Credencial,
                   espera_rechazo_ms: int = 15_000) -> None:
    # Se parte SIEMPRE sin sesion: una sesion residual de otro contribuyente haria declarar sobre el equivocado.
    context.clear_cookies()
    page.goto(login_url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(sel.LOGIN_USUARIO, state="attached", timeout=10_000)
    except PWTimeout:
        raise LoginError(f"No aparecio el formulario de login (URL: {url_corta(page.url)})") from None

    _escribir(page, sel.LOGIN_USUARIO, cred.ruc, "RUC")
    _escribir(page, sel.LOGIN_CLAVE, cred.clave, "clave")
    page.click(sel.LOGIN_ENVIAR)
    log.info("Login enviado: %s", cred)

    try:
        page.wait_for_url(lambda u: sel.LOGIN_RUTA not in u, timeout=espera_rechazo_ms)
    except PWTimeout:
        # Ambiguo (clave mala, portal lento, captcha): se trata como rechazo para no arriesgar el bloqueo de la cuenta.
        raise CredentialsRejected(
            f"El portal no acepto el login (sigue en {url_corta(page.url)}); no se reintenta"
        ) from None
    for _ in range(ESTABLE_S):
        page.wait_for_timeout(1000)
        if sel.LOGIN_RUTA in page.url:
            raise LoginError(f"El portal cerro la sesion tras el login (volvio a {url_corta(page.url)})")
    log.info("Login correcto")
