"""Pasos del formulario de IVA. Cada paso verifica su postcondicion antes de continuar."""
import re
import getpass

from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import Error as PWError

from src.sri import selectors as sel
from src.utils.exceptions import ObligacionNoDisponible, PasoNoMapeado, PeriodoNoCoincide, PortalChanged
from src.utils.logger import get_logger
from src.utils.validators import hoy_ecuador, nombre_mes

log = get_logger(__name__)


def seleccionar_obligacion(page: Page, codigo: str = sel.OBLIGACION_IVA) -> None:
    widget = page.locator(sel.OBLIGACION_WIDGET)
    widget.click()
    opcion = page.locator(sel.opcion_obligacion(codigo))
    try:
        opcion.first.wait_for(state="visible", timeout=5_000)
    except PWTimeout:
        raise ObligacionNoDisponible(f"La obligacion {codigo} no aparece en la lista del contribuyente") from None
    if opcion.count() != 1:
        raise PortalChanged(f"Se esperaba 1 opcion que empiece por {codigo} y hay {opcion.count()}")
    opcion.click()
    try:
        expect(widget.locator(sel.OBLIGACION_ETIQUETA)).to_contain_text(
            re.compile(rf"^\s*{codigo}\b"), timeout=5_000)
    except AssertionError:
        raise PortalChanged("La obligacion no quedo seleccionada") from None
    log.info("Obligacion seleccionada: %s", codigo)


def seleccionar_periodo(page: Page, anio: int, mes: int) -> None:
    """El periodo lo calcula el codigo; el resaltado del portal es solo verificacion cruzada."""
    if anio != hoy_ecuador().year:
        raise PasoNoMapeado("Periodo de otro anio (enero): el selector de anio aun no esta mapeado")

    campo = page.locator(sel.PERIODO_CAMPO)
    try:
        expect(campo).to_be_visible(timeout=8_000)
    except AssertionError:
        raise PortalChanged("No aparecio el campo del periodo") from None
    log.info("Valor previo del campo de periodo: '%s'", campo.input_value())
    campo.click()

    tabla = page.locator(sel.MES_TABLA)
    try:
        tabla.wait_for(state="visible", timeout=8_000)
    except PWTimeout:
        raise PasoNoMapeado("El selector de meses no se abrio al pulsar el campo del periodo") from None

    nombre = nombre_mes(mes)
    resaltados = tabla.locator(sel.MES_RESALTADO)
    if resaltados.count() != 1:
        raise PeriodoNoCoincide(f"El portal resalta {resaltados.count()} meses; se esperaba 1")
    resaltado = resaltados.first.inner_text().strip()
    if resaltado != nombre:
        raise PeriodoNoCoincide(f"Calculado: {nombre}; resaltado por el portal: {resaltado}")

    boton = tabla.get_by_role("button", name=nombre, exact=True)
    if "ui-state-disabled" in (boton.get_attribute("class") or ""):
        raise PeriodoNoCoincide(f"El mes {nombre} esta deshabilitado en el portal")
    boton.click()

    patron = re.compile(rf"^\s*{mes:02d}\s*/\s*(?:{anio}|{anio % 100:02d})\s*$")
    try:
        expect(campo).to_have_value(patron, timeout=5_000)
    except AssertionError:
        raise PortalChanged(f"El campo del periodo quedo con '{campo.input_value()}'") from None
    log.info("Periodo seleccionado: %s %s", nombre, anio)


def _verificar_seleccion(page: Page, anio: int, mes: int) -> None:
    """Precondicion de Siguiente: obligacion y periodo realmente elegidos en pantalla."""
    etiqueta = page.locator(sel.OBLIGACION_WIDGET).locator(sel.OBLIGACION_ETIQUETA).inner_text(timeout=3_000)
    if not re.match(rf"^\s*{sel.OBLIGACION_IVA}\b", etiqueta):
        raise PortalChanged("Antes de Siguiente la obligacion no esta seleccionada")
    valor = page.locator(sel.PERIODO_CAMPO).input_value(timeout=3_000)
    if not re.fullmatch(rf"\s*{mes:02d}\s*/\s*(?:{anio}|{anio % 100:02d})\s*", valor):
        raise PeriodoNoCoincide(f"Antes de Siguiente el periodo en pantalla es '{valor}'")


def siguiente(page: Page, anio: int, mes: int) -> None:
    _verificar_seleccion(page, anio, mes)
    boton = page.locator(sel.BOTON_SIGUIENTE)
    _esperar_ajax(page, 5_000)  # elegir el periodo dispara un ajax que vuelve a pintar el boton
    try:
        boton.wait_for(state="visible", timeout=10_000)
        expect(boton).to_be_enabled(timeout=10_000)
        expect(boton).not_to_have_class(re.compile(r"ui-state-disabled"), timeout=2_000)
    except (PWTimeout, AssertionError):
        raise PortalChanged("El boton Siguiente no esta disponible tras elegir el periodo") from None
    boton.click()
    _esperar_ajax(page, 10_000)
    log.info("Clic en Siguiente")

def _esperar_ajax(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PWTimeout:
        pass

def _log_cuestionario(page: Page) -> None:
    """Deja en el log cada pregunta del cuestionario y su respuesta actual (solo diagnostico)."""
    try:
        filas = page.locator(sel.PREGUNTA_FILA)
        for i in range(filas.count()):
            fila = filas.nth(i)
            texto = fila.locator("span.estilo-pregunta-padre-hija").first.inner_text(timeout=1_000).strip()
            marcado = fila.locator('input[type="radio"]:checked')
            valor = marcado.first.get_attribute("value") if marcado.count() else "-"
            log.info("Pregunta %d: %s -> %s", i, texto[:80], valor)
    except PWError:
        log.warning("No se pudo listar el cuestionario")


def responder_valores_no(page: Page) -> None:
    """Deja '¿Requiere informar valores en su declaracion?' en NO y verifica el estado final."""
    filas = page.locator(sel.PREGUNTA_FILA).filter(has_text=sel.PREGUNTA_VALORES)
    try:
        filas.first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        raise PasoNoMapeado("No aparecio la pregunta de informar valores tras Siguiente") from None
    if filas.count() != 1:
        raise PortalChanged(f"Se esperaba 1 pregunta de informar valores y hay {filas.count()}")
    _log_cuestionario(page)

    fila = filas.first
    no = fila.locator('input[type="radio"][value="NO"]')
    si = fila.locator('input[type="radio"][value="SI"]')
    if no.count() != 1 or si.count() != 1:
        raise PortalChanged("La pregunta no tiene exactamente las opciones SI y NO")

    estado = "NO" if no.is_checked() else ("SI" if si.is_checked() else "ninguno")
    log.info("Estado inicial de la pregunta de valores: %s", estado)
    if estado != "NO":
        no.locator("xpath=ancestor::td[1]//label").click()
        _esperar_ajax(page, 10_000)
    try:
        expect(no).to_be_checked(timeout=5_000)
        expect(si).not_to_be_checked(timeout=2_000)
    except AssertionError:
        raise PortalChanged("La respuesta NO no quedo marcada") from None
    if page.locator(sel.DIALOGO_MENSAJES).is_visible():
        raise PasoNoMapeado("El portal mostro un mensaje al responder: revise la captura")
    log.info("Pregunta de valores: NO")

def siguiente_perfilador(page: Page) -> None:
    """Siguiente del cuestionario hacia la pantalla de firma. No firma ni envia nada."""
    fila = page.locator(sel.PREGUNTA_FILA).filter(has_text=sel.PREGUNTA_VALORES)
    if fila.count() != 1 or not fila.first.locator('input[type="radio"][value="NO"]').is_checked():
        raise PortalChanged("Antes de Siguiente la respuesta NO no esta marcada")
    boton = page.locator(sel.BOTON_PERFILADOR_SIGUIENTE)
    try:
        boton.wait_for(state="visible", timeout=10_000)
        expect(boton).to_be_enabled(timeout=10_000)
        expect(boton).not_to_have_class(re.compile(r"ui-state-disabled"), timeout=2_000)
    except (PWTimeout, AssertionError):
        raise PortalChanged("El boton Siguiente del cuestionario no esta disponible") from None
    boton.click()
    _esperar_ajax(page, 10_000)
    if page.locator(sel.DIALOGO_MENSAJES).is_visible():
        raise PasoNoMapeado("El portal mostro un mensaje al pulsar Siguiente: revise la captura")
    try:
        expect(fila).to_be_hidden(timeout=15_000)
    except AssertionError:
        raise PortalChanged("El portal no avanzo tras Siguiente: la pregunta sigue visible") from None
    log.info("Clic en Siguiente del cuestionario")
