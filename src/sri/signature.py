"""Firma del contador: marca 'Si', escribe RUC y clave y SE DETIENE antes de Aceptar (ese clic envia la declaracion)."""
import re

from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import Error as PWError

from src.security.credential_repository import Credencial
from src.sri.declaration import _esperar_ajax
from src.utils.exceptions import ConfigError, ContadorRechazado, LoginError, PasoNoMapeado, PortalChanged
from src.utils.logger import get_logger

log = get_logger(__name__)

# Los ids de la pregunta llevan indices generados (repeatCuestionario:29): se busca por texto.
PREGUNTA_CONTADOR = "Requiere firma de contador"
PANEL_CONTADOR = '[id="frmFlujoDeclaracion:panelContador"]'  # la pregunta tambien puede existir fuera de este panel
CONTADOR_RUC = '[id="frmFlujoDeclaracion:txtRucContador"]'
CONTADOR_CLAVE = '[id="frmFlujoDeclaracion:txtPassContador"]'
CONTADOR_NOMBRES = '[id="frmFlujoDeclaracion:divApellidosNombresContador"]'
CONTADOR_MSG_RUC = '[id="frmFlujoDeclaracion:msgRucContador"]'
BOTON_ACEPTAR = '[id="frmFlujoDeclaracion:divBotonContinuarConfirmacion"]'


def _describir_radios(fila) -> str:
    """Para el log cuando algo falla: solo atributos tecnicos de los radios, nunca datos del contribuyente."""
    try:
        radios = fila.locator('input[type="radio"]')
        return "; ".join(f"value={radios.nth(k).get_attribute('value')!r} marcado={radios.nth(k).is_checked()}"
                         for k in range(radios.count())) or "(sin radios)"
    except PWError:
        return "(no se pudo leer)"


def _marcar_si(page: Page) -> None:
    # Fila = ancestro mas cercano de la pregunta que contiene los radios. Solo se busca dentro del panel del
    # contador y entre lo visible: la misma pregunta puede aparecer repetida en otras partes del DOM.
    fila = (page.locator(PANEL_CONTADOR)
            .locator(f"xpath=.//span[contains(normalize-space(.), '{PREGUNTA_CONTADOR}')]"
                     "/ancestor::div[.//input[@type='radio']][1]")
            .filter(visible=True))
    try:
        fila.first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        raise PasoNoMapeado("No aparecio la pregunta de firma de contador") from None
    if fila.count() != 1:
        log.warning("Filas visibles de la pregunta de firma de contador: %d", fila.count())
        raise PortalChanged(f"Se esperaba 1 pregunta de firma de contador y hay {fila.count()}")
    si = fila.locator('input[type="radio"][value="SI"]')
    no = fila.locator('input[type="radio"][value="NO"]')
    if si.count() != 1 or no.count() != 1:
        log.warning("Radios de la pregunta de firma de contador: %s", _describir_radios(fila))
        raise PortalChanged("La pregunta de firma de contador no tiene exactamente las opciones SI y NO")

    log.info("Estado inicial de la pregunta de firma de contador: %s",
             "SI" if si.is_checked() else ("NO" if no.is_checked() else "ninguno"))
    if not si.is_checked():
        # Primero la caja visual del radio: es lo que pulsa una persona. La etiqueta queda como alternativa.
        caja = si.locator("xpath=ancestor::div[contains(@class,'ui-radiobutton')][1]"
                          "//div[contains(@class,'ui-radiobutton-box')]")
        if caja.count() == 1:
            caja.click()
        else:
            si.locator("xpath=ancestor::td[1]//label").click()
        _esperar_ajax(page, 10_000)
    try:
        expect(si).to_be_checked(timeout=5_000)
        expect(no).not_to_be_checked(timeout=2_000)
    except AssertionError:
        log.warning("Radios tras pulsar SI: %s", _describir_radios(fila))
        raise PortalChanged("La respuesta SI de firma de contador no quedo marcada") from None


def _estado_nombres(div) -> tuple[str, str]:
    if div.count() == 0:
        return "", ""
    texto = div.inner_text().strip()
    valores = "".join(div.locator("input").evaluate_all("els => els.map(e => e.value)")).strip()
    return texto, valores


def llenar_contador(page: Page, contador: Credencial) -> None:
    """Deja listos los datos del contador. NO pulsa Aceptar."""
    if not re.fullmatch(r"\d{13}", contador.ruc):
        raise ConfigError("El RUC del contador debe tener 13 digitos")
    if any(ord(c) < 32 for c in contador.clave):
        raise ConfigError("La clave del contador contiene caracteres de control (un salto de linea enviaria el formulario)")
    _marcar_si(page)

    ruc = page.locator(CONTADOR_RUC)
    try:
        ruc.wait_for(state="visible", timeout=10_000)
    except PWTimeout:
        raise PasoNoMapeado("No aparecio el campo del RUC del contador tras marcar SI") from None

    nombres = page.locator(CONTADOR_NOMBRES)
    antes_texto, _ = _estado_nombres(nombres)
    ruc.click()
    ruc.press_sequentially(contador.ruc, delay=40)  # el campo solo admite digitos por teclado
    if ruc.input_value() != contador.ruc:
        raise LoginError("El campo RUC del contador no recibio el texto completo")
    ruc.press("Tab")  # el blur dispara el ajax que carga apellidos y nombres
    _esperar_ajax(page, 5_000)

    mensaje = page.locator(CONTADOR_MSG_RUC)
    for _ in range(34):  # ~10 s
        if mensaje.count() and mensaje.first.is_visible() and mensaje.first.inner_text().strip():
            raise ContadorRechazado("El portal rechazo el RUC del contador")
        texto, valores = _estado_nombres(nombres)
        hay_inputs = nombres.locator("input").count() > 0
        if (hay_inputs and valores) or (not hay_inputs and texto and texto != antes_texto):
            break
        page.wait_for_timeout(300)
    else:
        raise PortalChanged("El portal no cargo los apellidos y nombres del contador")

    clave = page.locator(CONTADOR_CLAVE)
    clave.click()
    clave.press_sequentially(contador.clave, delay=40)
    if len(clave.input_value()) != len(contador.clave):
        raise LoginError("La clave del contador no se escribio completa")

    boton = page.locator(BOTON_ACEPTAR)
    try:
        boton.wait_for(state="visible", timeout=5_000)
        expect(boton).to_be_enabled(timeout=3_000)
    except (PWTimeout, AssertionError):
        raise PortalChanged("El boton Aceptar no esta disponible") from None
    log.info("Datos del contador listos (%s). NO se pulsa Aceptar: ese clic envia la declaracion", contador)
