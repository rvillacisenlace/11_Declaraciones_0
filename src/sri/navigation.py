from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from config import settings
from src.sri import selectors as sel
from src.utils.exceptions import LoginError
from src.utils.logger import get_logger
from src.utils.validators import url_corta

log = get_logger(__name__)


def abrir_login(page: Page) -> None:
    page.goto(settings.SRI_LOGIN_URL, wait_until="domcontentloaded")


def abrir_formulario_iva(page: Page) -> None:
    """Se entra al formulario DESPUES de tener sesion (abrirlo antes hace que el portal la cierre)."""
    try:
        page.goto(settings.FORM_IVA_URL, wait_until="domcontentloaded")
    except PWError as e:
        if "interrupted by another navigation" not in str(e):
            raise
        log.warning("Navegacion interrumpida por una redireccion del portal")
    try:
        page.locator(sel.OBLIGACION_WIDGET).wait_for(state="visible", timeout=20_000)
    except PWTimeout:
        raise LoginError(
            f"No aparecio el formulario de IVA (URL: {url_corta(page.url)}): "
            "sesion no iniciada o enlace cambiado"
        ) from None
    log.info("Formulario de IVA abierto")
