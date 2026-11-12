"""Zero 0.2: un fideicomiso (--contribuyente) o un lote (--lote). Solo el lote con --enviar envia declaraciones reales."""
"""Zero 0.2: un fideicomiso (--contribuyente) o un lote (--lote). Solo el lote con --enviar envia declaraciones reales."""
import argparse
import getpass
import os
import re
import sys
from collections import Counter

from config import settings
from src.core.process_queue import procesar_lote
from src.database.models import Estado
from src.database.repository import Repositorio
from src.security import credential_repository
from src.security.credential_repository import Credencial
from src.services.control_writer import marcar_declarado
from src.services.fideicomiso_service import cruzar_credenciales, leer_control, ruta_control
from src.sri import authentication, declaration, navigation, retenciones, signature, submission
from src.sri.browser import open_context
from src.utils.evidence import capturar
from src.utils.exceptions import AlreadyDeclared, ConfigError, ZeroError
from src.utils.logger import configurar_logging, get_logger
from src.utils.rutas import carpeta_declaracion, carpeta_evidencia
from src.utils.validators import nombre_mes, periodo_a_declarar

log = get_logger("zero")


def _validacion_previa(cid: str, periodo: tuple[int, int]) -> None:
    """Hasta que exista el archivo de control, la validacion humana se confirma aqui y queda en el log."""
    print(f"\nContribuyente: {cid} | Periodo: {nombre_mes(periodo[1])} {periodo[0]}")
    if input("Confirma que NO tuvo movimiento en ese periodo? Escriba SI: ").strip() != "SI":
        raise ZeroError("Sin validacion previa de 'sin movimiento'")
    log.info("validacion_previa contribuyente=%s periodo=%s-%02d por=%s",
             cid, periodo[0], periodo[1], getpass.getuser())


def _marca(impuesto: str) -> str:
    """Columna del Control que decide que se procesa: DECLARA_0 (IVA) o RETENCION_0 (retenciones)."""
    return "retencion_0" if impuesto == "1031" else "declara_0"


def _fideicomiso(cid: str, marca: str = "declara_0"):
    """Busca el ID en el Control y exige que sea procesable (la marca SI y datos validos)."""
    r = leer_control(ruta_control(), marca)
    for p in r.pendientes:
        if p.id == cid:
            return p
    for e in r.excluidos:
        if e.id == cid:
            raise ConfigError(f"El fideicomiso {cid} esta excluido: {e.motivo}")
    raise ConfigError(f"El fideicomiso {cid} no esta marcado con SI en {marca.upper()} (o no existe en el Control)")


def _cargar_credenciales(cid: str, login: str, con_contador: bool, clave_maestra: str, marca: str = "declara_0"):
    """Devuelve (credencial del fideicomiso o None, credencial del contador o None). Cruce por RUC."""
    cred = contador = None
    if login == "auto":
        fid = _fideicomiso(cid, marca)
        cred = credential_repository.cargar_contribuyente(fid.id, fid.ruc, clave_maestra)
    if con_contador:
        contador = credential_repository.cargar_contador(clave_maestra)
    return cred, contador


def _datos_carpeta(args, cred):
    """(ruc, responsable) para ubicar las capturas. Con login manual no hay datos: se usa el ID y SIN RESPONSABLE."""
    if args.credenciales == "excel" and args.login == "auto":
        fid = _fideicomiso(args.contribuyente, _marca(args.impuesto))
        return fid.ruc, fid.responsable
    return (cred.ruc if cred else None), None


def _pedir(id_: str, tipo: str) -> Credencial:
    """Pide RUC y clave por consola. La clave no se muestra ni se guarda en ningun archivo."""
    ruc = input(f"RUC del {tipo}: ").strip()
    clave = getpass.getpass(f"Clave del {tipo} (no se muestra): ")
    if not ruc or not clave:
        raise ConfigError(f"Faltan datos del {tipo}")
    if tipo == "contador" and not re.fullmatch(r"\d{13}", ruc):
        raise ConfigError("El RUC del contador debe tener 13 digitos")
    return Credencial(id=id_, tipo=tipo, ruc=ruc, clave=clave)


def _credenciales_por_consola(cid: str, login: str, con_contador: bool):
    """Solo desarrollo, mientras no haya acceso al Excel cifrado. Pide unicamente lo que el flujo va a usar."""
    log.warning("Credenciales por consola: uso solo para desarrollo")
    cred = _pedir(cid, "contribuyente") if login == "auto" else None
    contador = _pedir("contador", "contador") if con_contador else None
    return cred, contador


def _flujo(ctx, page, cid: str, periodo: tuple[int, int], hasta: str, cred, contador, *, enviar: bool = False,
           ruc: str | None = None, responsable: str | None = None) -> str | None:
    """Recorrido del IVA. Capturas: una por pantalla, justo antes de cada clic (Siguiente, Siguiente, Aceptar, Imprimir)."""
    evid = carpeta_evidencia(responsable, ruc or cid)

    def foto(paso: str) -> None:
        capturar(page, evid, periodo, paso, "2011")

    if cred is None:  # solo desarrollo
        navigation.abrir_login(page)
        input("\nInicie sesion MANUALMENTE en la ventana de Edge (un solo intento) y presione ENTER... ")
    else:
        authentication.iniciar_sesion(ctx, page, settings.SRI_LOGIN_URL, cred)
    navigation.abrir_formulario_iva(page)

    declaration.seleccionar_obligacion(page)
    declaration.seleccionar_periodo(page, *periodo)
    foto("01_periodo")  # antes de Siguiente
    if hasta == "periodo":
        return

    declaration.siguiente(page, *periodo)
    declaration.rechazar_si_ya_declarado(page, evidencia=lambda: foto("ya_declarado"))  # si ya esta declarado: Rechazar
    if hasta == "siguiente":
        return

    declaration.responder_valores_no(page)
    foto("02_preguntas")  # antes del Siguiente del cuestionario
    if hasta == "valores":
        return

    declaration.siguiente_perfilador(page)
    if hasta == "firma":
        return

    signature.llenar_contador(page, contador)  # NO pulsa Aceptar: ese clic envia la declaracion
    retenciones.verificar_sin_recargos(page)  # interes y multa deben ser 0; si no, no seria una declaracion en cero
    foto("03_resumen")  # antes de Aceptar
    if not enviar:
        return None

    # ENVIO REAL: solo se llega aqui con --enviar, DRY_RUN=false y las dos confirmaciones escritas del lote.
    destino = carpeta_declaracion(responsable, ruc, "2011")
    comprobante = submission.enviar_declaracion(page, ruc, periodo, destino, envio_autorizado=True,
                                                evidencia=lambda: foto("04_confirmacion"))  # antes de Imprimir
    return f"comprobante serie {comprobante.name.split('_')[0]}"

def _ejecutar_lote(args, periodo: tuple[int, int]) -> int:
    """Procesa todos los fideicomisos marcados con SI que pasan las validaciones y tienen credencial."""
    if args.enviar and settings.DRY_RUN:
        raise ZeroError("DRY_RUN=true en el .env: el envio real esta bloqueado")
    r = leer_control(ruta_control(), _marca(args.impuesto))
    clave = getpass.getpass("Contrasena del archivo de credenciales: ")
    listos, extra = cruzar_credenciales(r.pendientes, clave)
    marcados = len(r.pendientes) + len(r.excluidos)
    print(f"\nImpuesto: {args.impuesto} | Periodo: {nombre_mes(periodo[1])} {periodo[0]} | marcados SI: {marcados} | "
          f"listos: {len(listos)} | excluidos: {len(r.excluidos) + len(extra)}")
    for resp, n in sorted(Counter(f.responsable for f in listos).items()):
        print(f"  {n:4d}  {resp}")
    if not listos:
        print("No hay fideicomisos para procesar.")
        return 0
    if input(f"Confirma que los {len(listos)} fideicomisos NO tuvieron movimiento? Escriba SI: ").strip() != "SI":
        raise ZeroError("Sin validacion previa del lote")
    log.info("validacion_previa_lote n=%d periodo=%s-%02d por=%s", len(listos), periodo[0], periodo[1], getpass.getuser())
    if args.enviar:
        n = min(len(listos), args.max)
        nombre = "retenciones" if args.impuesto == "1031" else "IVA"
        if input(f"Se ENVIARAN hasta {n} declaraciones REALES de {nombre} al SRI y no se pueden deshacer. Escriba ENVIAR: ").strip() != "ENVIAR":
            raise ZeroError("Envio no confirmado")
        log.warning("envio_real_confirmado n=%d periodo=%s-%02d por=%s", n, periodo[0], periodo[1], getpass.getuser())

    contador = credential_repository.cargar_contador(clave) if args.hasta == "contador" else None
    estado_ok = Estado.DECLARADO if args.enviar else (Estado.SIMULADO if args.hasta == "contador" else Estado.PARCIAL)
   
    def reflejar_en_control(f, estado):
        """DECLARADO y YA_DECLARADO se anotan como DECLARADO en la celda del impuesto (solo si decia SI)."""
        if ruta_control() is not None:
            marcar_declarado(ruta_control(), f.fila, f.id, _marca(args.impuesto), settings.DATA_DIR / "respaldos")
    
    with Repositorio(settings.DATA_DIR / "execution_history.db") as repo:
        ejec = repo.iniciar_ejecucion(settings.VERSION, settings.DRY_RUN, f"{args.hasta} ({args.impuesto})",
                                      f"{periodo[0]}-{periodo[1]:02d}", getpass.getuser())
        with open_context() as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def ejecutar(fid):
                cred = credential_repository.cargar_contribuyente(fid.id, fid.ruc, clave)
                extra = {"ruc": fid.ruc, "responsable": fid.responsable}
                if args.enviar:
                    extra["enviar"] = True
                try:
                    if args.impuesto == "1031":
                        return retenciones.recorrer(ctx, page, fid.id, periodo, args.hasta, cred, contador, **extra)
                    return _flujo(ctx, page, fid.id, periodo, args.hasta, cred, contador, **extra)
                except AlreadyDeclared:
                    raise  # resultado esperado: ya tiene su propia captura (ya_declarado); otra de error seria basura
                except Exception:
                    try:
                        capturar(page, carpeta_evidencia(fid.responsable, fid.ruc), periodo, "error", args.impuesto)
                    except Exception:
                        log.warning("No se pudo capturar la pantalla de error")
                    raise

            res = procesar_lote(listos, periodo, repo, ejecutar, ejec, estado_ok=estado_ok, max_n=args.max,
                                pausa_s=args.pausa, incluir_revision=args.incluir_revision, impuesto=args.impuesto,
                                al_terminar=reflejar_en_control)
        repo.cerrar_ejecucion(ejec, res.resumen())
    print("\n" + res.resumen())
    return 3 if res.detenido else 0

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="zero")
    ap.add_argument("--contribuyente", help="ID del Control (un solo fideicomiso)")
    ap.add_argument("--lote", action="store_true", help="procesa todos los fideicomisos marcados con SI")
    ap.add_argument("--max", type=int, help="maximo de fideicomisos en esta ejecucion (lotes pequenos)")
    ap.add_argument("--pausa", type=float, default=float(os.getenv("PAUSA_ENTRE_S", "30")),
                    help="segundos de espera entre fideicomisos (se le suma una variacion al azar)")
    ap.add_argument("--incluir-revision", action="store_true", help="reintenta tambien los de revision manual")
    ap.add_argument("--enviar", action="store_true",
                    help="ENVIA las declaraciones de verdad (exige --lote, --max N, --hasta contador y DRY_RUN=false)")
    ap.add_argument("--impuesto", choices=("2011", "1031"), default="2011",
                    help="2011 = IVA (por defecto); 1031 = retenciones")
    ap.add_argument("--hasta", choices=("periodo", "siguiente", "valores", "firma", "contador"), default="periodo")
    ap.add_argument("--credenciales", choices=("excel", "consola"), default="excel",
                    help="excel: archivo cifrado (produccion); consola: se piden por teclado (solo desarrollo)")
    ap.add_argument("--login", choices=("auto", "manual"), default="auto",
                    help="auto: credenciales del Excel cifrado (produccion); manual: solo desarrollo")
    args = ap.parse_args(argv)
    if bool(args.contribuyente) == args.lote:
        ap.error("indique --contribuyente o --lote (uno solo)")
    if args.contribuyente and not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.contribuyente):
        ap.error("--contribuyente solo admite letras, numeros, guion y guion bajo")
    if args.lote and (args.login != "auto" or args.credenciales != "excel"):
        ap.error("--lote requiere --login auto y --credenciales excel")
    if args.max is not None and args.max < 1:
        ap.error("--max debe ser 1 o mayor")

    if args.enviar and not (args.lote and args.max and args.hasta == "contador"):
        ap.error("--enviar requiere --lote, --max N y --hasta contador")

    configurar_logging()
    periodo = periodo_a_declarar()
    log.info("Zero %s | DRY_RUN=%s | periodo=%s-%02d | hasta=%s",
             settings.VERSION, settings.DRY_RUN, periodo[0], periodo[1], args.hasta)
    try:
        settings.validar()
        if args.lote:
            return _ejecutar_lote(args, periodo)
        _validacion_previa(args.contribuyente, periodo)
        con_contador = args.hasta == "contador"
        cred = contador = None
        if args.credenciales == "consola":
            cred, contador = _credenciales_por_consola(args.contribuyente, args.login, con_contador)
        elif args.login == "auto" or con_contador:
            cred, contador = _cargar_credenciales(
                args.contribuyente, args.login, con_contador,
                getpass.getpass("Contrasena del archivo de credenciales: "), _marca(args.impuesto))
        ruc, responsable = _datos_carpeta(args, cred)
        with open_context() as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                recorrido = retenciones.recorrer if args.impuesto == "1031" else _flujo
                recorrido(ctx, page, args.contribuyente, periodo, args.hasta, cred, contador,
                          ruc=ruc, responsable=responsable)
            except AlreadyDeclared:
                raise  # resultado esperado: ya tiene su propia captura (ya_declarado); otra de error seria basura
            except Exception:
                capturar(page, carpeta_evidencia(responsable, ruc or args.contribuyente), periodo, "error", args.impuesto)
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