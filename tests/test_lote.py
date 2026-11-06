from dataclasses import dataclass

import pytest

from src.core.process_queue import procesar_lote
from src.database.models import Estado
from src.database.repository import Repositorio
from src.utils.exceptions import (AlreadyDeclared, CaptchaRejected, ComprobanteInvalido, ConfigError,
                                  ContadorRechazado, CredentialsRejected, ObligacionNoDisponible, PasoNoMapeado,
                                  PeriodoNoCoincide, PortalChanged)

P = (2026, 10)
TXT = "2026-10"


@dataclass
class F:
    id: str


@pytest.fixture
def repo():
    r = Repositorio(":memory:")
    yield r
    r.cerrar()


def correr(repo, ids, comportamiento=None, **kw):
    """comportamiento: {id: excepcion}. Devuelve (resultado, ids ejecutados en orden)."""
    comportamiento = comportamiento or {}
    vistos = []

    def ejecutar(f):
        vistos.append(f.id)
        if f.id in comportamiento:
            raise comportamiento[f.id]

    kw.setdefault("estado_ok", Estado.SIMULADO)
    return procesar_lote([F(i) for i in ids], P, repo, ejecutar, 1, **kw), vistos


def test_todo_bien(repo):
    res, vistos = correr(repo, ["1", "2", "3"])
    assert vistos == ["1", "2", "3"] and res.por_estado == {"simulado": 3} and res.detenido is None
    assert all(repo.estado(i, TXT) == Estado.SIMULADO for i in vistos)


def test_estado_parcial_cuando_el_flujo_se_corta_a_proposito(repo):
    res, _ = correr(repo, ["1"], estado_ok=Estado.PARCIAL)
    assert repo.estado("1", TXT) == Estado.PARCIAL


def test_omite_finales_y_revision_manual(repo):
    repo.marcar("1", TXT, Estado.DECLARADO)
    repo.marcar("2", TXT, Estado.YA_DECLARADO)
    repo.marcar("3", TXT, Estado.OBLIGACION_NO_DISPONIBLE)
    repo.marcar("4", TXT, Estado.REVISION_MANUAL)
    repo.marcar("5", TXT, Estado.ERROR)
    res, vistos = correr(repo, ["1", "2", "3", "4", "5", "6"])
    assert vistos == ["6", "5"] and res.omitidos == 4  # el nuevo (6) va antes que el que dio error (5)


def test_incluir_revision_reintenta_esos(repo):
    repo.marcar("4", TXT, Estado.REVISION_MANUAL)
    repo.marcar("1", TXT, Estado.DECLARADO)
    _, vistos = correr(repo, ["1", "4"], incluir_revision=True)
    assert vistos == ["4"]


def test_un_declarado_nunca_se_repite_aunque_se_corra_dos_veces(repo):
    repo.marcar("1", TXT, Estado.DECLARADO)
    for _ in range(2):
        _, vistos = correr(repo, ["1"])
        assert vistos == []


def test_ya_declarado_y_obligacion_no_disponible_no_son_fallos(repo):
    res, vistos = correr(repo, ["1", "2", "3", "4", "5"], {
        "1": AlreadyDeclared("x"), "2": ObligacionNoDisponible("x"), "3": AlreadyDeclared("x"),
        "4": ObligacionNoDisponible("x"), "5": AlreadyDeclared("x")}, max_fallos_seguidos=2)
    assert res.detenido is None and len(vistos) == 5
    assert repo.estado("2", TXT) == Estado.OBLIGACION_NO_DISPONIBLE and repo.estado("1", TXT) == Estado.YA_DECLARADO


def test_portal_cambiado_detiene_al_instante(repo):
    res, vistos = correr(repo, ["1", "2", "3"], {"2": PortalChanged("selector")})
    assert vistos == ["1", "2"] and "portal" in res.detenido
    assert repo.estado("2", TXT) == Estado.REVISION_MANUAL
    assert repo.estado("3", TXT) is None


def test_paso_no_mapeado_detiene_al_instante(repo):
    res, vistos = correr(repo, ["1", "2"], {"1": PasoNoMapeado("pantalla nueva")})
    assert vistos == ["1"] and res.detenido


def test_contador_rechazado_detiene_todo(repo):
    res, vistos = correr(repo, ["1", "2", "3"], {"1": ContadorRechazado("x")})
    assert vistos == ["1"] and "contador" in res.detenido
    assert repo.estado("1", TXT) == Estado.ERROR


def test_credencial_rechazada_de_un_fideicomiso_no_detiene_el_lote(repo):
    res, vistos = correr(repo, ["1", "2", "3"], {"2": CredentialsRejected("x")})
    assert vistos == ["1", "2", "3"] and res.detenido is None
    assert repo.estado("2", TXT) == Estado.ERROR and repo.estado("3", TXT) == Estado.SIMULADO


def test_tres_fallos_seguidos_detienen_el_lote(repo):
    comp = {i: CredentialsRejected("x") for i in ("2", "3", "4")}
    res, vistos = correr(repo, ["1", "2", "3", "4", "5", "6"], comp)
    assert vistos == ["1", "2", "3", "4"] and "3 fallos seguidos" in res.detenido


def test_un_exito_reinicia_el_contador_de_fallos(repo):
    comp = {"1": RuntimeError("x"), "2": RuntimeError("x"), "4": RuntimeError("x"), "5": RuntimeError("x")}
    res, vistos = correr(repo, ["1", "2", "3", "4", "5", "6"], comp)
    assert res.detenido is None and len(vistos) == 6


def test_captcha_y_periodo_distinto_van_a_revision_y_cuentan_como_fallo(repo):
    res, vistos = correr(repo, ["1", "2", "3", "4"], {
        "1": CaptchaRejected("x"), "2": PeriodoNoCoincide("x"), "3": CaptchaRejected("x")})
    assert vistos == ["1", "2", "3"] and res.detenido
    assert all(repo.estado(i, TXT) == Estado.REVISION_MANUAL for i in "123")


def test_error_de_configuracion_de_uno_no_cuenta_para_detener(repo):
    comp = {i: ConfigError("sin clave") for i in "1234"}
    res, vistos = correr(repo, ["1", "2", "3", "4", "5"], comp)
    assert res.detenido is None and len(vistos) == 5 and repo.estado("1", TXT) == Estado.ERROR


def test_max_limita_el_lote(repo):
    _, vistos = correr(repo, ["1", "2", "3", "4"], max_n=2)
    assert vistos == ["1", "2"] and repo.estado("3", TXT) is None


def test_pausa_entre_fideicomisos_pero_no_antes_del_primero(repo):
    esperas = []
    correr(repo, ["1", "2", "3"], pausa_s=10, dormir=esperas.append, azar=lambda a, b: b)
    assert esperas == [15.0, 15.0]


def test_ctrl_c_deja_el_actual_en_revision_y_vuelve_a_lanzar(repo):
    with pytest.raises(KeyboardInterrupt):
        correr(repo, ["1", "2"], {"1": KeyboardInterrupt()})
    assert repo.estado("1", TXT) == Estado.REVISION_MANUAL and repo.estado("2", TXT) is None


def test_una_ejecucion_caida_deja_en_revision_lo_que_estaba_en_proceso(repo):
    repo.marcar("1", TXT, Estado.EN_PROCESO, intento=True)  # el programa murio a medias
    res, vistos = correr(repo, ["1", "2"])
    assert vistos == ["2"] and repo.estado("1", TXT) == Estado.REVISION_MANUAL


def test_el_resumen_nombra_el_motivo_de_la_parada(repo):
    res, _ = correr(repo, ["1"], {"1": ContadorRechazado("x")})
    assert "DETENIDO" in res.resumen()


def test_con_max_el_lote_avanza_y_no_repite_los_ya_simulados(repo):
    repo.marcar("1", TXT, Estado.SIMULADO)
    repo.marcar("2", TXT, Estado.SIMULADO)
    _, vistos = correr(repo, ["1", "2", "3", "4"], max_n=2)
    assert vistos == ["3", "4"]


def test_orden_nuevos_luego_error_luego_simulados(repo):
    repo.marcar("1", TXT, Estado.SIMULADO)
    repo.marcar("2", TXT, Estado.ERROR)
    _, vistos = correr(repo, ["1", "2", "3"])
    assert vistos == ["3", "2", "1"]


def test_cuando_ya_se_simularon_todos_vuelve_a_empezar(repo):
    for i in ("1", "2"):
        repo.marcar(i, TXT, Estado.SIMULADO)
    _, vistos = correr(repo, ["1", "2"])
    assert vistos == ["1", "2"]


def test_comprobante_invalido_detiene_el_lote_y_deja_revision_manual(repo):
    res, vistos = correr(repo, ["1", "2", "3"], {"1": ComprobanteInvalido("x")})
    assert vistos == ["1"] and "comprobante" in res.detenido
    assert repo.estado("1", TXT) == Estado.REVISION_MANUAL