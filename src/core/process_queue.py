"""Orquestador de un lote. No conoce el navegador: recibe 'ejecutar(fideicomiso)' y decide, segun lo que ocurra,
el estado de cada declaracion y cuando detener el lote."""
import random
import time
from collections import Counter
from dataclasses import dataclass, field

from src.database.models import FINALES, Estado
from src.utils.exceptions import (AlreadyDeclared, CaptchaRejected, ComprobanteInvalido, ConfigError,
                                  ContadorRechazado, EnvioIncierto, ObligacionNoDisponible, PasoNoMapeado,
                                  PeriodoNoCoincide, PortalChanged)
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
    detenido: str | None = None

    def resumen(self) -> str:
        estados = ", ".join(f"{k}={v}" for k, v in sorted(self.por_estado.items())) or "sin cambios"
        return (f"procesados={self.procesados} omitidos={self.omitidos} [{estados}]"
                + (f" | DETENIDO: {self.detenido}" if self.detenido else ""))


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
    if isinstance(e, (PeriodoNoCoincide, CaptchaRejected)):
        return Estado.REVISION_MANUAL, "fallo", None
    if isinstance(e, ConfigError):
        return Estado.ERROR, "neutro", None
    return Estado.ERROR, "fallo", None  # credenciales rechazadas, login, imprevistos

def procesar_lote(fideicomisos, periodo: tuple, repo, ejecutar, ejecucion_id: int, *, estado_ok: Estado,
                  max_n: int | None = None, pausa_s: float = 0.0, max_fallos_seguidos: int = 3,
                  incluir_revision: bool = False, impuesto: str = "2011", dormir=time.sleep,
                  azar=random.uniform) -> ResultadoLote:
    txt = f"{periodo[0]}-{periodo[1]:02d}"
    res, conteo = ResultadoLote(), Counter()
    recuperadas = repo.recuperar_interrumpidas(txt, ejecucion_id)
    if recuperadas:
        log.warning("%d declaracion(es) de una ejecucion interrumpida pasaron a revision manual", recuperadas)

    omitir = set(FINALES) | (set() if incluir_revision else {Estado.REVISION_MANUAL})
    cola = []
    for f in fideicomisos:
        estado = repo.estado(f.id, txt, impuesto)
        if estado in omitir:
            res.omitidos += 1
        else:
            cola.append((PRIORIDAD.get(estado, 2), f))
    cola = [f for _, f in sorted(cola, key=lambda x: x[0])]  # estable: respeta el orden del Control
    if max_n:
        cola = cola[:max_n]

    fallos = 0
    for k, f in enumerate(cola):
        if k and pausa_s:
            dormir(pausa_s + azar(0, pausa_s / 2))  # espaciado con variacion: no procesar en rafaga
        repo.marcar(f.id, txt, Estado.EN_PROCESO, ejecucion_id=ejecucion_id, intento=True, impuesto=impuesto)
        res.procesados += 1
        try:
            detalle_ok = ejecutar(f)
        except KeyboardInterrupt:
            repo.marcar(f.id, txt, Estado.REVISION_MANUAL, "interrumpido por el operador: verificar en el SRI",
                        ejecucion_id, impuesto=impuesto)
            raise
        except Exception as e:
            estado, efecto, motivo = _clasificar(e)
            repo.marcar(f.id, txt, estado, f"{type(e).__name__}: {e}", ejecucion_id, impuesto=impuesto)
            conteo[estado.value] += 1
            log.warning("Fideicomiso %s -> %s (%s)", f.id, estado.value, type(e).__name__)
            if efecto == "stop":
                res.detenido = motivo
                break
            fallos = fallos + 1 if efecto == "fallo" else (0 if efecto == "reset" else fallos)
            if fallos >= max_fallos_seguidos:
                res.detenido = f"{fallos} fallos seguidos: se detiene el lote"
                break
        else:
            repo.marcar(f.id, txt, estado_ok, detalle_ok or "", ejecucion_id, impuesto=impuesto)
            conteo[estado_ok.value] += 1
            log.info("Fideicomiso %s -> %s", f.id, estado_ok.value)
            fallos = 0
    res.por_estado = dict(conteo)
    log.info("Lote terminado: %s", res.resumen())
    return res