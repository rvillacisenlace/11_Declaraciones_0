"""El lote avanza por FIDEICOMISO: IVA y retenciones seguidos, con un solo inicio de sesion, y recien despues el siguiente."""
from dataclasses import dataclass

import pytest

import main
from src.core.process_queue import procesar_por_fideicomiso
from src.database.models import Estado
from src.database.repository import Repositorio
from src.services.fideicomiso_service import Fideicomiso, ResultadoControl
from src.sri import retenciones
from src.utils.exceptions import AlreadyDeclared, CredentialsRejected, PortalChanged, RecargosInesperados
from tests import test_main_lote as _base

entorno = _base.entorno  # settings, credenciales y confirmaciones simuladas
P, TXT = (2026, 10), "2026-10"


@dataclass
class F:
    id: str


@pytest.fixture
def repo():
    r = Repositorio(":memory:")
    yield r
    r.cerrar()


def correr(repo, grupos, comportamiento=None, **kw):
    """comportamiento: {(id, impuesto): excepcion}. Devuelve (resultado, [(id, impuesto)] en orden de ejecucion)."""
    comportamiento = comportamiento or {}
    vistos = []

    def ejecutar(f, imp):
        vistos.append((f.id, imp))
        if (f.id, imp) in comportamiento:
            raise comportamiento[(f.id, imp)]

    kw.setdefault("estado_ok", Estado.SIMULADO)
    return procesar_por_fideicomiso(grupos, P, repo, ejecutar, 1, **kw), vistos


def G(*pares):
    return [(F(i), tuple(imps)) for i, imps in pares]


DOS = ("2011", "1031")


# ------------------------------------------------------------------ orden y pausa
def test_cada_fideicomiso_hace_sus_dos_impuestos_antes_de_pasar_al_siguiente(repo):
    res, vistos = correr(repo, G(("A", DOS), ("B", DOS)))
    assert vistos == [("A", "2011"), ("A", "1031"), ("B", "2011"), ("B", "1031")]
    assert res["2011"].procesados == 2 and res["1031"].procesados == 2


def test_solo_marcado_en_retenciones_hace_solo_retenciones(repo):
    _, vistos = correr(repo, G(("A", DOS), ("B", ("1031",)), ("C", ("2011",))))
    assert vistos == [("A", "2011"), ("A", "1031"), ("B", "1031"), ("C", "2011")]


def test_la_pausa_es_entre_fideicomisos_no_entre_impuestos(repo):
    pausas = []
    correr(repo, G(("A", DOS), ("B", DOS), ("C", DOS)), pausa_s=10, dormir=pausas.append, azar=lambda a, b: 0)
    assert pausas == [10, 10]  # 3 fideicomisos -> 2 pausas (con 6 declaraciones)


# ------------------------------------------------------------------ --max cuenta declaraciones
def test_max_cuenta_declaraciones_y_corta_dentro_de_un_fideicomiso(repo):
    res, vistos = correr(repo, G(("A", DOS), ("B", DOS)), max_n=3)
    assert vistos == [("A", "2011"), ("A", "1031"), ("B", "2011")]
    assert res["2011"].procesados == 2 and res["1031"].procesados == 1


# ------------------------------------------------------------------ omitidos y prioridad
def test_lo_ya_declarado_de_un_impuesto_se_omite_y_se_hace_el_otro(repo):
    repo.marcar("A", TXT, Estado.DECLARADO, impuesto="2011")
    res, vistos = correr(repo, G(("A", DOS), ("B", DOS)))
    assert vistos == [("A", "1031"), ("B", "2011"), ("B", "1031")] and res["2011"].omitidos == 1


def test_un_fideicomiso_con_algo_nuevo_va_antes_que_uno_que_ya_fallo(repo):
    repo.marcar("A", TXT, Estado.ERROR, impuesto="2011")
    repo.marcar("A", TXT, Estado.ERROR, impuesto="1031")
    _, vistos = correr(repo, G(("A", DOS), ("B", DOS)))
    assert vistos[0] == ("B", "2011")


# ------------------------------------------------------------------ fallos
def test_si_el_primer_impuesto_falla_no_se_intenta_el_segundo_de_ese_fideicomiso(repo):
    res, vistos = correr(repo, G(("A", DOS), ("B", DOS)), {("A", "2011"): CredentialsRejected("clave")})
    assert vistos == [("A", "2011"), ("B", "2011"), ("B", "1031")]
    assert repo.estado("A", TXT, "1031") is None  # sin tocar: queda pendiente para otra ejecucion
    assert repo.estado("A", TXT, "2011") == Estado.ERROR


def test_un_fallo_inesperado_en_el_segundo_impuesto_no_afecta_al_siguiente_fideicomiso(repo):
    _, vistos = correr(repo, G(("A", DOS), ("B", DOS)), {("A", "1031"): RecargosInesperados("multa")})
    assert vistos == [("A", "2011"), ("A", "1031"), ("B", "2011"), ("B", "1031")]
    assert repo.estado("A", TXT, "1031") == Estado.REVISION_MANUAL


def test_ya_declarado_en_iva_si_sigue_con_retenciones(repo):
    res, vistos = correr(repo, G(("A", DOS)), {("A", "2011"): AlreadyDeclared("ya")})
    assert vistos == [("A", "2011"), ("A", "1031")]
    assert repo.estado("A", TXT, "2011") == Estado.YA_DECLARADO and repo.estado("A", TXT, "1031") == Estado.SIMULADO


def test_un_problema_general_detiene_todo(repo):
    res, vistos = correr(repo, G(("A", DOS), ("B", DOS)), {("A", "2011"): PortalChanged("selector")})
    assert vistos == [("A", "2011")] and res["2011"].detenido


def test_tres_fallos_seguidos_detienen_el_lote(repo):
    comp = {(i, "2011"): CredentialsRejected("x") for i in "ABC"}
    res, vistos = correr(repo, G(("A", DOS), ("B", DOS), ("C", DOS), ("D", DOS)), comp)
    assert vistos == [("A", "2011"), ("B", "2011"), ("C", "2011")] and "3 fallos" in res["2011"].detenido


# ------------------------------------------------------------------ Control
def test_al_terminar_recibe_el_impuesto_de_cada_declaracion(repo):
    avisos = []
    correr(repo, G(("A", DOS)), estado_ok=Estado.DECLARADO, al_terminar=lambda f, e, imp: avisos.append((f.id, imp)))
    assert avisos == [("A", "2011"), ("A", "1031")]


# ------------------------------------------------------------------ main: un solo login por fideicomiso
@pytest.fixture
def dos_impuestos(entorno, monkeypatch):
    llamadas, tmp = entorno
    fids = [Fideicomiso(2, "A1", "N", "1790000000001", "R1"), Fideicomiso(3, "A2", "N", "1790000000002", "R2")]
    solo_ret = [Fideicomiso(3, "A2", "N", "1790000000002", "R2")]
    marcas = {"declara_0": fids, "retencion_0": fids}
    monkeypatch.setattr(main, "leer_control", lambda _r, m="declara_0": ResultadoControl(5, 3, marcas[m], []))
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    eventos = []
    monkeypatch.setattr(main, "_flujo", lambda ctx, page, cid, per, hasta, cred, cont, **kw:
                        eventos.append((cid, "2011", kw.get("sesion_iniciada", False))))
    monkeypatch.setattr(retenciones, "recorrer", lambda ctx, page, cid, per, hasta, cred, cont, **kw:
                        eventos.append((cid, "1031", kw.get("sesion_iniciada", False))))
    return llamadas, marcas, solo_ret, eventos


def test_main_recorre_por_fideicomiso_y_solo_inicia_sesion_en_el_primer_impuesto(dos_impuestos):
    llamadas, _, _, eventos = dos_impuestos
    assert main.main(["--lote", "--hasta", "periodo", "--pausa", "0"]) == 0
    assert eventos == [("A1", "2011", False), ("A1", "1031", True), ("A2", "2011", False), ("A2", "1031", True)]
    assert llamadas["creds"] == ["A1", "A2"]  # la credencial se descifra una vez por fideicomiso


def test_main_si_el_iva_esta_omitido_las_retenciones_inician_sesion_ellas(dos_impuestos):
    llamadas, _, _, eventos = dos_impuestos
    with Repositorio(main.settings.DATA_DIR / "execution_history.db") as r:
        r.marcar("A1", "2026-10", Estado.DECLARADO, impuesto="2011")
    assert main.main(["--lote", "--hasta", "periodo", "--pausa", "0"]) == 0
    assert eventos[0] == ("A1", "1031", False)


def test_main_fideicomiso_marcado_solo_en_retenciones(dos_impuestos):
    _, marcas, solo_ret, eventos = dos_impuestos
    marcas["retencion_0"] = solo_ret + marcas["declara_0"][:1]  # A2 y A1; IVA: A1 y A2
    marcas["declara_0"] = marcas["declara_0"][:1]  # IVA: solo A1
    assert main.main(["--lote", "--hasta", "periodo", "--pausa", "0"]) == 0
    assert eventos == [("A1", "2011", False), ("A1", "1031", True), ("A2", "1031", False)]


def test_main_max_limita_declaraciones_no_fideicomisos(dos_impuestos):
    _, _, _, eventos = dos_impuestos
    assert main.main(["--lote", "--hasta", "periodo", "--pausa", "0", "--max", "3"]) == 0
    assert [(c, i) for c, i, _ in eventos] == [("A1", "2011"), ("A1", "1031"), ("A2", "2011")]


def test_un_fideicomiso_con_algun_impuesto_nuevo_no_espera_detras_de_los_que_solo_tienen_errores(repo):
    for imp in DOS:
        repo.marcar("B", TXT, Estado.ERROR, impuesto=imp)  # B: todo con error
    repo.marcar("A", TXT, Estado.ERROR, impuesto="2011")  # A: IVA con error, retenciones nuevas
    _, vistos = correr(repo, G(("B", DOS), ("A", DOS), ("C", DOS)))
    assert [i for i, _ in vistos] == ["A", "A", "C", "C", "B", "B"]  # B (solo errores) va al final


def test_main_anota_en_el_control_cada_impuesto_en_su_columna(dos_impuestos, monkeypatch):
    _, _, _, eventos = dos_impuestos
    anotados = []
    monkeypatch.setattr(main, "ruta_control", lambda: "control.xlsx")
    monkeypatch.setattr(main, "marcar_declarado", lambda ruta, fila, id_, marca, resp: anotados.append((id_, marca)))
    ya = lambda *a, **k: (_ for _ in ()).throw(AlreadyDeclared("ya"))  # noqa: E731
    monkeypatch.setattr(main, "_flujo", ya)
    monkeypatch.setattr(retenciones, "recorrer", ya)
    assert main.main(["--lote", "--hasta", "periodo", "--pausa", "0", "--max", "2"]) == 0
    assert anotados == [("A1", "declara_0"), ("A1", "retencion_0")]
