"""Orquestador de un lote. No conoce el navegador: recibe 'ejecutar(fideicomiso)' y decide, segun lo que ocurra,
el estado de cada declaracion y cuando detener el lote."""
import random
import time
from collections import Counter
from dataclasses import dataclass, field

from src.database.models import FINALES, Estado
from src.utils.exceptions import (AlreadyDeclared, CaptchaRejected, ComprobanteInvalido, ConfigError,
                                  ContadorRechazado, EnvioIncierto, ObligacionNoDisponible, PasoNoMapeado,
                                  PeriodoNoCoincide, PortalChanged, RecargosInesperados)
from src.utils.logger import get_logger

log = get_logger(__name__)


# Orden de la cola: primero los nunca intentados; luego los que fallaron; al final los ya simulados o parciales
# (no son finales, pero con --max el lote debe avanzar en lugar de repetir siempre los mismos).
PRIORIDAD = {None: 0, Estado.PENDIENTE: 0, Estado.ERROR: 1, Estado.PARCIAL: 2, Estado.SIMULADO: 2,
             Estado.REVISION_MANUAL: 3}


@dataclass
class ResultadoLote:
    omitidos: int = 0
    procesados: int = 0
    por_estado: dict = field(default_factory=dict)
    omitidos_por_estado: dict = field(default_factory=dict)  # por que se omitio: {estado de la base: cantidad}
    detenido: str | None = None

    def resumen(self) -> str:
        estados = ", ".join(f"{k}={v}" for k, v in sorted(self.por_estado.items())) or "sin cambios"
        motivo = ", ".join(f"{k}: {v}" for k, v in sorted(self.omitidos_por_estado.items()))
        return (f"procesados={self.procesados} omitidos={self.omitidos}" + (f" ({motivo})" if motivo else "")
                + f" [{estados}]" + (f" | DETENIDO: {self.detenido}" if self.detenido else ""))


def _clasificar(e: Exception):
    """(estado, efecto, motivo). efecto: reset (limpia fallos seguidos), neutro, fallo (suma) o stop (detiene el lote)."""
    if isinstance(e, AlreadyDeclared):
        return Estado.YA_DECLARADO, "reset", None
    if isinstance(e, ObligacionNoDisponible):
        return Estado.OBLIGACION_NO_DISPONIBLE, "reset", None
    if isinstance(e, ContadorRechazado):
        return Estado.ERROR, "stop", "el portal rechazo al contador que firma: afecta a todos los fideicomisos"
    if isinstance(e, (ComprobanteInvalido, EnvioIncierto)):
        return Estado.REVISION_MANUAL, "stop", "no se pudo confirmar el envio o su comprobante: la declaracion pudo enviarse, verifique en el SRI"
    if isinstance(e, (PortalChanged, PasoNoMapeado)):
        return Estado.REVISION_MANUAL, "stop", f"el portal no respondio como se esperaba ({type(e).__name__})"
    if isinstance(e, (PeriodoNoCoincide, CaptchaRejected, RecargosInesperados)):
        return Estado.REVISION_MANUAL, "fallo", None
    if isinstance(e, ConfigError):
        return Estado.ERROR, "neutro", None
    return Estado.ERROR, "fallo", None  # credenciales rechazadas, login, imprevistos

def _avisar(al_terminar, f, estado: Estado) -> None:
    """Avisa de un estado final (declarado / ya declarado) para reflejarlo en el Control. Si falla, el lote sigue."""
    if al_terminar is None or estado not in (Estado.DECLARADO, Estado.YA_DECLARADO):
        return
    try:
        al_terminar(f, estado)
    except Exception as e:
        log.warning("No se pudo reflejar el estado de %s en el Control (%s): marquelo a mano", f.id, type(e).__name__)


def procesar_por_fideicomiso(grupos, periodo: tuple, repo, ejecutar, ejecucion_id: int, *, estado_ok: Estado,
                             max_n: int | None = None, pausa_s: float = 0.0, max_fallos_seguidos: int = 3,
                             incluir_revision: bool = False, al_terminar=None,
                             dormir=time.sleep, azar=random.uniform) -> dict:
    """Cola por FIDEICOMISO: grupos = [(fideicomiso, (impuestos...))]. De cada fideicomiso se hacen todos sus impuestos
    seguidos (ejecutar(f, impuesto)) y recien despues se pasa al siguiente: un solo inicio de sesion por fideicomiso.
    Si un impuesto falla de forma inesperada, no se sigue con el otro de ese fideicomiso en esta ejecucion (la sesion
    pudo quedar mal); solo se sigue tras un exito o un resultado esperado (ya declarado / obligacion no disponible).
    max_n cuenta declaraciones, no fideicomisos. Devuelve {impuesto: ResultadoLote}."""
    txt = f"{periodo[0]}-{periodo[1]:02d}"
    res = {imp: ResultadoLote() for _, imps in grupos for imp in imps}
    conteo = {imp: Counter() for imp in res}
    recuperadas = repo.recuperar_interrumpidas(txt, ejecucion_id)
    if recuperadas:
        log.warning("%d declaracion(es) de una ejecucion interrumpida pasaron a revision manual", recuperadas)

    omitir = set(FINALES) | (set() if incluir_revision else {Estado.REVISION_MANUAL})
    cola = []
    for f, imps in grupos:
        pendientes = []
        for imp in imps:
            estado = repo.estado(f.id, txt, imp)
            if estado in omitir:
                res[imp].omitidos += 1
                res[imp].omitidos_por_estado[estado.value] = res[imp].omitidos_por_estado.get(estado.value, 0) + 1
                # Si la base ya lo da por declarado pero el Control sigue en SI (anotacion que fallo antes), se corrige aqui.
                _avisar(None if al_terminar is None else (lambda fid, est, i=imp: al_terminar(fid, est, i)), f, estado)
            else:
                pendientes.append((PRIORIDAD.get(estado, 2), imp))
        if pendientes:
            cola.append((min(p for p, _ in pendientes), f, [imp for _, imp in pendientes]))
    cola.sort(key=lambda x: x[0])  # estable: respeta el orden del Control
    if max_n:
        recortada, restante = [], max_n
        for p, f, imps in cola:
            if restante < 1:
                break
            recortada.append((p, f, imps[:restante]))
            restante -= len(imps[:restante])
        cola = recortada

    fallos, parar = 0, False
    for k, (_, f, imps) in enumerate(cola):
        if k and pausa_s:
            dormir(pausa_s + azar(0, pausa_s / 2))  # espaciado con variacion entre fideicomisos, no en rafaga
        for j, imp in enumerate(imps):
            r = res[imp]
            repo.marcar(f.id, txt, Estado.EN_PROCESO, ejecucion_id=ejecucion_id, intento=True, impuesto=imp)
            r.procesados += 1
            try:
                detalle_ok = ejecutar(f, imp)
            except KeyboardInterrupt:
                repo.marcar(f.id, txt, Estado.REVISION_MANUAL, "interrumpido por el operador: verificar en el SRI",
                            ejecucion_id, impuesto=imp)
                raise
            except Exception as e:
                estado, efecto, motivo = _clasificar(e)
                repo.marcar(f.id, txt, estado, f"{type(e).__name__}: {e}", ejecucion_id, impuesto=imp)
                conteo[imp][estado.value] += 1
                log.warning("Fideicomiso %s (%s) -> %s (%s: %s)", f.id, imp, estado.value, type(e).__name__, str(e)[:200])
                _avisar(None if al_terminar is None else (lambda fid, est, i=imp: al_terminar(fid, est, i)), f, estado)
                if efecto == "stop":
                    r.detenido, parar = motivo, True
                    break
                fallos = fallos + 1 if efecto == "fallo" else (0 if efecto == "reset" else fallos)
                if fallos >= max_fallos_seguidos:
                    r.detenido, parar = f"{fallos} fallos seguidos: se detiene el lote", True
                    break
                if efecto != "reset":
                    if imps[j + 1:]:
                        log.warning("Fideicomiso %s: no se intenta %s tras el fallo de %s (se reintenta en otra ejecucion)",
                                    f.id, ", ".join(imps[j + 1:]), imp)
                    break
            else:
                repo.marcar(f.id, txt, estado_ok, detalle_ok or "", ejecucion_id, impuesto=imp)
                conteo[imp][estado_ok.value] += 1
                log.info("Fideicomiso %s (%s) -> %s", f.id, imp, estado_ok.value)
                _avisar(None if al_terminar is None else (lambda fid, est, i=imp: al_terminar(fid, est, i)), f, estado_ok)
                fallos = 0
        if parar:
            break
    for imp, r in res.items():
        r.por_estado = dict(conteo[imp])
        log.info("Lote terminado (%s): %s", imp, r.resumen())
    return res


def procesar_lote(fideicomisos, periodo: tuple, repo, ejecutar, ejecucion_id: int, *, estado_ok: Estado,
                  max_n: int | None = None, pausa_s: float = 0.0, max_fallos_seguidos: int = 3,
                  incluir_revision: bool = False, impuesto: str = "2011", al_terminar=None,
                  dormir=time.sleep, azar=random.uniform) -> ResultadoLote:
    """Un solo impuesto (cola de un fideicomiso por vez). Es el caso particular de procesar_por_fideicomiso."""
    res = procesar_por_fideicomiso(
        [(f, (impuesto,)) for f in fideicomisos], periodo, repo, lambda f, _imp: ejecutar(f), ejecucion_id,
        estado_ok=estado_ok, max_n=max_n, pausa_s=pausa_s, max_fallos_seguidos=max_fallos_seguidos,
        incluir_revision=incluir_revision, al_terminar=None if al_terminar is None else (lambda f, e, _i: al_terminar(f, e)),
        dormir=dormir, azar=azar)
    return res.get(impuesto, ResultadoLote())
