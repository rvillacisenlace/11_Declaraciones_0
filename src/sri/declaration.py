"""Pasos del formulario de IVA. Cada paso verifica su postcondicion antes de continuar."""
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PWTimeout

from src.sri import selectors as sel
from src.utils.exceptions import ObligacionNoDisponible, PasoNoMapeado, PeriodoNoCoincide, PortalChanged
from src.utils.logger import get_logger
from src.utils.validators import hoy_ecuador, nombre_mes

log = get_logger(__name__)


def seleccionar_obligacion(page: Page, nombre: str = sel.OBLIGACION_IVA) -> None:
    widget = page.locator(sel.OBLIGACION_WIDGET)
    widget.click()
    opcion = page.locator(sel.opcion_obligacion(nombre))
    try:
        opcion.wait_for(state="visible", timeout=5_000)
    except PWTimeout:
        raise ObligacionNoDisponible(f"'{nombre}' no aparece en la lista del contribuyente") from None
    opcion.click()
    try:
        expect(widget.locator(sel.OBLIGACION_ETIQUETA)).to_contain_text(nombre, timeout=5_000)
    except AssertionError:
        raise PortalChanged("La obligacion no quedo seleccionada") from None
    log.info("Obligacion seleccionada: %s", nombre)


def seleccionar_periodo(page: Page, anio: int, mes: int) -> None:
    """El periodo lo calcula el codigo; el resaltado del portal es solo verificacion cruzada."""
    if anio != hoy_ecuador().year:
        raise PasoNoMapeado("Periodo de otro anio (enero): el selector de anio aun no esta mapeado")
    tabla = page.locator(sel.MES_TABLA)
    try:
        tabla.wait_for(state="visible", timeout=8_000)
    except PWTimeout:
        raise PasoNoMapeado("El selector de meses no esta visible: falta mapear como se abre") from None

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
    log.info("Periodo seleccionado: %s %s", nombre, anio)


def siguiente(page: Page) -> None:
    boton = page.get_by_role("button", name=sel.BOTON_SIGUIENTE, exact=True)
    n = boton.count()
    if n != 1:
        raise PortalChanged(f"Se esperaba 1 boton 'Siguiente' y hay {n}")
    boton.click()
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PWTimeout:
        pass
    log.info("Clic en Siguiente")
