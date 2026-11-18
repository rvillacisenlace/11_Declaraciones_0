from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from config import settings
from src.sri import selectors as sel
from src.utils.exceptions import LoginError, PortalChanged
from src.utils.logger import get_logger
from src.utils.validators import url_corta

log = get_logger(__name__)


_INICIO = {"url": None}  # pagina con el menu, a la que se llega justo despues del login


def abrir_login(page: Page) -> None:
    page.goto(settings.SRI_LOGIN_URL, wait_until="domcontentloaded")


def recordar_inicio(page: Page) -> None:
    """Guarda la pagina del menu (la de despues del login) para volver a ella con la sesion ya abierta."""
    _INICIO["url"] = page.url


def volver_al_inicio(page: Page) -> None:
    """Con la sesion reutilizada para un segundo impuesto, la pantalla del formulario anterior ya no trae el menu:
    se vuelve a la pagina del menu SIN iniciar sesion otra vez (no se tocan las cookies)."""
    url = _INICIO["url"]
    if not url:
        log.warning("No se conoce la pagina de inicio: se intenta abrir el formulario desde la pantalla actual")
        return
    log.info("Se vuelve al inicio del portal: %s", url_corta(url))
    page.goto(url, wait_until="domcontentloaded")


def esperar_formulario_iva(page: Page) -> None:
    try:
        page.locator(sel.OBLIGACION_WIDGET).wait_for(state="visible", timeout=20_000)
    except PWTimeout:
        raise LoginError(
            f"No aparecio el formulario de IVA (URL: {url_corta(page.url)}): "
            "sesion no iniciada o menu cambiado"
        ) from None
    log.info("Formulario de IVA abierto")


def abrir_formulario_iva(page: Page) -> None:
    """Se llega por el menu, como una persona: el enlace directo el portal lo devuelve a la pagina publica."""
    log.info("URL antes de abrir el formulario: %s", url_corta(page.url))
    recordar_inicio(page)
    opcion = page.get_by_text(sel.MENU_FORMULARIO_IVA, exact=True)
    try:
        opcion.first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        raise LoginError(
            f"No aparecio la opcion '{sel.MENU_FORMULARIO_IVA}' (URL: {url_corta(page.url)}): "
            "sesion no iniciada o menu cambiado"
        ) from None
    n = opcion.count()
    if n != 1:
        raise PortalChanged(f"Se esperaba 1 opcion '{sel.MENU_FORMULARIO_IVA}' y hay {n}")
    opcion.click()
    esperar_formulario_iva(page)