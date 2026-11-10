"""Retenciones en la fuente (1031): recorrido de PRUEBA, solo hasta antes de 'Aceptar'.
Este modulo NO puede enviar: no usa el boton Aceptar. Existe para descubrir, sin riesgo, como se comporta ese
formulario (texto de la pregunta, respuesta por defecto, recargos). El envio de retenciones se habilitara cuando
exista un comprobante real con el que verificarlo. Reutiliza los pasos genericos del IVA (obligacion, periodo)."""
import re

from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PWTimeout

from config import settings
from src.sri import authentication, declaration, navigation, signature
from src.sri import selectors as sel
from src.utils.evidence import capturar
from src.utils.exceptions import LoginError, PasoNoMapeado, PeriodoNoCoincide, PortalChanged, RecargosInesperados
from src.utils.logger import get_logger
from src.utils.validators import url_corta

log = get_logger(__name__)

CODIGO = "1031"
MENU = "Formulario de Retenciones en la Fuente"
CAMPOS_RECARGO = {"interes": '[id="frmFlujoDeclaracion:valorInteres_input"]',
                  "multa": '[id="frmFlujoDeclaracion:valorMulta_input"]'}


def abrir_formulario(page: Page) -> None:
    log.info("URL antes de abrir el formulario de retenciones: %s", url_corta(page.url))
    opcion = page.get_by_text(MENU, exact=True)
    try:
        opcion.first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        raise LoginError(f"No aparecio la opcion '{MENU}' (URL: {url_corta(page.url)})") from None
    if opcion.count() != 1:
        raise PortalChanged(f"Se esperaba 1 opcion '{MENU}' y hay {opcion.count()}")
    opcion.click()
    try:
        page.locator(sel.OBLIGACION_WIDGET).wait_for(state="visible", timeout=20_000)
    except PWTimeout:
        raise LoginError(f"No aparecio el formulario de retenciones (URL: {url_corta(page.url)})") from None
    log.info("Formulario de retenciones abierto")


def _verificar_seleccion(page: Page, anio: int, mes: int) -> None:
    etiqueta = page.locator(sel.OBLIGACION_WIDGET).locator(sel.OBLIGACION_ETIQUETA).inner_text(timeout=3_000)
    if not re.match(rf"^\s*{CODIGO}\b", etiqueta):
        raise PortalChanged("Antes de Siguiente la obligacion 1031 no esta seleccionada")
    valor = page.locator(sel.PERIODO_CAMPO).input_value(timeout=3_000)
    if not re.fullmatch(rf"\s*{mes:02d}\s*/\s*(?:{anio}|{anio % 100:02d})\s*", valor):
        raise PeriodoNoCoincide(f"Antes de Siguiente el periodo en pantalla es '{valor}'")


def _pulsar(page: Page, selector: str, que: str) -> None:
    boton = page.locator(selector)
    try:
        boton.wait_for(state="visible", timeout=10_000)
        expect(boton).to_be_enabled(timeout=10_000)
        expect(boton).not_to_have_class(re.compile(r"ui-state-disabled"), timeout=2_000)
    except (PWTimeout, AssertionError):
        raise PortalChanged(f"El boton {que} no esta disponible") from None
    boton.click()
    declaration._esperar_ajax(page, 10_000)


def siguiente(page: Page, anio: int, mes: int) -> None:
    _verificar_seleccion(page, anio, mes)
    declaration._esperar_ajax(page, 5_000)  # elegir el periodo vuelve a pintar el boton por ajax
    _pulsar(page, sel.BOTON_SIGUIENTE, "Siguiente")
    log.info("Clic en Siguiente (retenciones)")


def responder_no(page: Page) -> None:
    """La pantalla de preguntas de retenciones tiene UNA sola pregunta: se localiza por estructura y se deja el
    texto en el log, porque aun no se conoce. Exige NO (retencion en cero) y verifica el estado final."""
    filas = page.locator(sel.PREGUNTA_FILA).filter(visible=True)
    try:
        filas.first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        raise PasoNoMapeado("No aparecio la pregunta de retenciones tras Siguiente") from None
    if filas.count() != 1:
        raise PortalChanged(f"Se esperaba 1 pregunta en retenciones y hay {filas.count()}")
    fila = filas.first
    texto = fila.locator("span.estilo-pregunta-padre-hija").first.inner_text(timeout=2_000).strip()
    si = fila.locator('input[type="radio"][value="SI"]')
    no = fila.locator('input[type="radio"][value="NO"]')
    if si.count() != 1 or no.count() != 1:
        log.warning("Radios de la pregunta de retenciones: %s", signature._describir_radios(fila))
        raise PortalChanged("La pregunta de retenciones no tiene exactamente las opciones SI y NO")
    estado = "NO" if no.is_checked() else ("SI" if si.is_checked() else "ninguno")
    log.info("Pregunta de retenciones: %s -> estado inicial %s", texto[:140], estado)
    if estado != "NO":
        caja = no.locator("xpath=ancestor::div[contains(@class,'ui-radiobutton')][1]"
                          "//div[contains(@class,'ui-radiobutton-box')]")
        if caja.count() == 1:
            caja.click()
        else:
            no.locator("xpath=ancestor::td[1]//label").click()
        declaration._esperar_ajax(page, 10_000)
    try:
        expect(no).to_be_checked(timeout=5_000)
        expect(si).not_to_be_checked(timeout=2_000)
    except AssertionError:
        raise PortalChanged("La respuesta NO de retenciones no quedo marcada") from None
    if page.locator(sel.DIALOGO_MENSAJES).is_visible():
        raise PasoNoMapeado("El portal mostro un mensaje al responder: revise la captura")


def siguiente_perfilador(page: Page) -> None:
    # La fila se distingue por su TEXTO: la pantalla siguiente (resumen) tambien trae filas con esa misma clase CSS.
    fila = page.locator(sel.PREGUNTA_FILA).filter(has_text=sel.PREGUNTA_VALORES)
    if fila.count() != 1 or not fila.first.locator('input[type="radio"][value="NO"]').is_checked():
        raise PortalChanged("Antes de Siguiente la respuesta NO no esta marcada")
    _pulsar(page, sel.BOTON_PERFILADOR_SIGUIENTE, "Siguiente del cuestionario")
    if page.locator(sel.DIALOGO_MENSAJES).is_visible():
        raise PasoNoMapeado("El portal mostro un mensaje al pulsar Siguiente: revise la captura")
    try:
        expect(fila).to_be_hidden(timeout=15_000)
    except AssertionError:
        raise PortalChanged("El portal no avanzo tras Siguiente: la pregunta sigue visible") from None
    log.info("Clic en Siguiente del cuestionario (retenciones)")


def verificar_sin_recargos(page: Page) -> None:
    """Antes de poder enviar, interes y multa deben ser cero; si no, la declaracion no seria en cero.
    Registra los valores que muestra el portal (son montos de la declaracion, no datos personales)."""
    for nombre, selector in CAMPOS_RECARGO.items():
        campo = page.locator(selector)
        if campo.count() == 0:
            log.info("Recargo '%s': el campo no existe en esta pantalla", nombre)
            continue
        valor = campo.first.input_value(timeout=3_000).strip()
        log.info("Recargo '%s' en pantalla: %r", nombre, valor)
        if re.search(r"[1-9]", valor):
            raise RecargosInesperados(f"El portal calculo {nombre} ({valor}): la declaracion no seria en cero")


def recorrer(ctx, page: Page, cid: str, periodo: tuple[int, int], hasta: str, cred, contador) -> None:
    """Recorrido de prueba de retenciones. NUNCA pulsa Aceptar."""
    if cred is None:  # solo desarrollo
        navigation.abrir_login(page)
        input("\nInicie sesion MANUALMENTE en la ventana de Edge (un solo intento) y presione ENTER... ")
    else:
        authentication.iniciar_sesion(ctx, page, settings.SRI_LOGIN_URL, cred)
    abrir_formulario(page)
    capturar(page, cid, periodo, "ret_01_formulario")

    declaration.seleccionar_obligacion(page, CODIGO)
    declaration.seleccionar_periodo(page, *periodo)
    capturar(page, cid, periodo, "ret_02_periodo")
    if hasta == "periodo":
        return

    siguiente(page, *periodo)
    capturar(page, cid, periodo, "ret_03_despues_siguiente")
    if hasta == "siguiente":
        return

    responder_no(page)
    capturar(page, cid, periodo, "ret_04_pregunta_no")
    if hasta == "valores":
        return

    siguiente_perfilador(page)
    capturar(page, cid, periodo, "ret_05_pantalla_firma")
    if hasta == "firma":
        return

    signature.llenar_contador(page, contador)
    verificar_sin_recargos(page)
    capturar(page, cid, periodo, "ret_06_contador_listo")