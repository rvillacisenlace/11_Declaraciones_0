"""Zero - corte vertical 0.1: login manual, formulario de IVA, obligacion y periodo."""
import argparse
import getpass
import re
import sys

from config import settings
from src.security import credential_repository
from src.sri import authentication, declaration, navigation, signature
from src.sri.browser import open_context
from src.utils.evidence import capturar
from src.utils.exceptions import ConfigError, ZeroError
from src.utils.logger import configurar_logging, get_logger
from src.utils.validators import nombre_mes, periodo_a_declarar

log = get_logger("zero")


def _validacion_previa(cid: str, periodo: tuple[int, int]) -> None:
    """Hasta que exista el archivo de control, la validacion humana se confirma aqui y queda en el log."""
    print(f"\nContribuyente: {cid} | Periodo: {nombre_mes(periodo[1])} {periodo[0]}")
    if input("Confirma que NO tuvo movimiento en ese periodo? Escriba SI: ").strip() != "SI":
        raise ZeroError("Sin validacion previa de 'sin movimiento'")
    log.info("validacion_previa contribuyente=%s periodo=%s-%02d por=%s",
             cid, periodo[0], periodo[1], getpass.getuser())


def _cargar_credenciales(cid: str, login: str, con_contador: bool, clave_maestra: str):
    """Devuelve (credencial del contribuyente o None, credencial del contador o None)."""
    cred = contador = None
    if login == "auto":
        cred = credential_repository.cargar(cid, clave_maestra)
    if con_contador:
        base = cred or credential_repository.cargar(cid, clave_maestra)
        if not base.contador_id:
            raise ConfigError(f"El contribuyente {cid} no tiene contador_id asignado")
        contador = credential_repository.cargar(base.contador_id, clave_maestra)
        if contador.tipo != "contador":
            raise ConfigError(f"La fila {base.contador_id} no es de tipo 'contador'")
    return cred, contador


def _flujo(ctx, page, cid: str, periodo: tuple[int, int], hasta: str, cred, contador) -> None:
    if cred is None:  # solo desarrollo
        navigation.abrir_login(page)
        input("\nInicie sesion MANUALMENTE en la ventana de Edge (un solo intento) y presione ENTER... ")
    else:
        authentication.iniciar_sesion(ctx, page, settings.SRI_LOGIN_URL, cred)
    navigation.abrir_formulario_iva(page)
    capturar(page, cid, periodo, "01_formulario")

    declaration.seleccionar_obligacion(page)
    declaration.seleccionar_periodo(page, *periodo)
    capturar(page, cid, periodo, "02_periodo")
    if hasta == "periodo":
        return

    declaration.siguiente(page, *periodo)
    capturar(page, cid, periodo, "03_despues_siguiente")
    if hasta == "siguiente":
        return

    declaration.responder_valores_no(page)
    capturar(page, cid, periodo, "04_valores_no")
    if hasta == "valores":
        return

    declaration.siguiente_perfilador(page)
    capturar(page, cid, periodo, "05_pantalla_firma")
    if hasta == "firma":
        return

    signature.llenar_contador(page, contador)  # NO pulsa Aceptar: ese clic envia la declaracion
    capturar(page, cid, periodo, "06_contador_listo")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="zero")
    ap.add_argument("--contribuyente", required=True, help="id interno (ni RUC ni nombre)")
    ap.add_argument("--hasta", choices=("periodo", "siguiente", "valores", "firma", "contador"), default="periodo")
    ap.add_argument("--login", choices=("auto", "manual"), default="auto",
                    help="auto: credenciales del Excel cifrado (produccion); manual: solo desarrollo")
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.contribuyente):
        ap.error("--contribuyente solo admite letras, numeros, guion y guion bajo")

    configurar_logging()
    periodo = periodo_a_declarar()
    log.info("Zero %s | DRY_RUN=%s | periodo=%s-%02d | hasta=%s",
             settings.VERSION, settings.DRY_RUN, periodo[0], periodo[1], args.hasta)
    try:
        settings.validar()
        _validacion_previa(args.contribuyente, periodo)
        con_contador = args.hasta == "contador"
        cred = contador = None
        if args.login == "auto" or con_contador:
            cred, contador = _cargar_credenciales(
                args.contribuyente, args.login, con_contador,
                getpass.getpass("Contrasena del archivo de credenciales: "))
        with open_context() as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                _flujo(ctx, page, args.contribuyente, periodo, args.hasta, cred, contador)
            except Exception:
                capturar(page, args.contribuyente, periodo, "error")
                raise
    except ZeroError as e:
        log.error("%s: %s", type(e).__name__, str(e)[:300])
        return 1
    except Exception:
        log.exception("Error inesperado")
        return 2
    log.info("Fin del flujo (sin enviar nada)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
