"""Envio de la declaracion: el UNICO lugar del programa donde se pulsa 'Aceptar' (ese clic ENVIA y no se deshace).
Candados: (1) el llamador debe declarar envio_autorizado=True; (2) un solo clic, sin reintentos; (3) el exito
se confirma con el mensaje del portal; (4) el comprobante se descarga, se verifica y se archiva.
Cualquier fallo DESPUES del clic se vuelve EnvioIncierto o ComprobanteInvalido: nunca un error comun,
porque un error comun se reintentaria y la declaracion pudo haberse enviado ya."""
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from src.sri import verification
from src.sri.signature import BOTON_ACEPTAR
from src.utils.exceptions import ComprobanteInvalido, ConfigError, EnvioIncierto, PortalChanged
from src.utils.logger import get_logger

log = get_logger(__name__)

MENSAJE_EXITO = '[id="mensajePrincipal"]'
TEXTO_EXITO = "procesada satisfactoriamente"
BOTON_IMPRIMIR = '[id="frmFlujoDeclaracion:btnDescargarComprobante"]'
ESPERA_EXITO_MS = 60_000
ESPERA_DESCARGA_MS = 30_000


def enviar_declaracion(page: Page, ruc: str, periodo: tuple[int, int], destino: Path, *, envio_autorizado: bool,
                       hoy: date | None = None, ahora: datetime | None = None) -> Path:
    """Pulsa Aceptar UNA vez, confirma el exito, descarga el comprobante y lo archiva. Devuelve su ruta."""
    if envio_autorizado is not True:
        raise ConfigError("Envio no autorizado: no se pulsa Aceptar")
    boton = page.locator(BOTON_ACEPTAR)
    try:
        boton.wait_for(state="visible", timeout=5_000)
    except PWTimeout:
        raise PortalChanged("El boton Aceptar no esta disponible") from None
    if not boton.is_enabled():
        raise PortalChanged("El boton Aceptar esta deshabilitado")

    log.warning("ENVIANDO la declaracion: un solo clic en Aceptar")
    try:
        boton.click()  # UNICO clic de envio de todo el programa
        try:
            page.locator(MENSAJE_EXITO).filter(has_text=TEXTO_EXITO).first.wait_for(
                state="visible", timeout=ESPERA_EXITO_MS)
        except PWTimeout:
            raise EnvioIncierto("El portal no confirmo el envio: la declaracion pudo haberse enviado") from None
        log.info("El portal confirmo: declaracion procesada")
        return _descargar_y_archivar(page, ruc, periodo, Path(destino), hoy, ahora)
    except (EnvioIncierto, ComprobanteInvalido):
        raise
    except Exception as e:
        raise EnvioIncierto(f"Fallo tras pulsar Aceptar ({type(e).__name__}): la declaracion pudo haberse enviado") from None


def _descargar_y_archivar(page: Page, ruc: str, periodo: tuple[int, int], destino: Path,
                          hoy: date | None, ahora: datetime | None) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    temporal = destino / f".descarga_{datetime.now():%Y%m%d%H%M%S%f}.tmp"
    try:
        with page.expect_download(timeout=ESPERA_DESCARGA_MS) as info:
            page.locator(BOTON_IMPRIMIR).click()
        info.value.save_as(str(temporal))
    except PWTimeout:
        raise ComprobanteInvalido("El portal confirmo el envio pero no se pudo descargar el comprobante") from None
    try:
        return verification.archivar(temporal, destino, ruc, periodo, ahora=ahora, hoy=hoy)
    except ComprobanteInvalido:
        # Se conserva el archivo para revision manual, con un nombre que no se confunda con un comprobante valido.
        temporal.replace(destino / f"RECHAZADO_{datetime.now():%Y%m%d%H%M%S}.pdf")
        raise