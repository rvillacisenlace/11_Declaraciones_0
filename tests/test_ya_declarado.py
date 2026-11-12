import inspect
import sqlite3
from pathlib import Path

import pytest
from openpyxl import Workbook
from playwright.sync_api import TimeoutError as PWTimeout

import main
from config import settings
from src.core.process_queue import _avisar
from src.database.models import Estado
from src.services.fideicomiso_service import leer_control
from src.sri import declaration as dec
from src.sri import retenciones
from src.sri import selectors as sel
from src.utils.exceptions import AlreadyDeclared, ConfigError, PortalChanged
from tests import test_main_envio as _envio
from tests import test_main_lote as _base
from tests.test_verificacion import PERIODO

entorno = _base.entorno  # fixture compartida (settings y credenciales simulados)


# ------------------------------------------------------------------ pagina falsa del aviso (Aceptar / Rechazar)
class _Dialogo:
    def __init__(self, texto):
        self.texto = texto

    def inner_text(self, timeout=None):
        return self.texto


class _Botones:
    def __init__(self, pagina, nombres=None):
        self.p = pagina
        self.nombres = list(pagina.botones if nombres is None else nombres)

    def filter(self, visible=None, has_text=None):
        if has_text is not None:
            return _Botones(self.p, [n for n in self.nombres if has_text.search(n)])
        return self

    def or_(self, otro):
        return _Union(self.p)

    def count(self):
        return len(self.nombres)

    @property
    def first(self):
        return self

    def locator(self, xpath):
        return _Dialogo(self.p.texto)

    def click(self):
        if self.p.falla_click:
            raise RuntimeError("no se pudo pulsar")
        self.p.clics.append(self.nombres[0])


class _Preguntas:
    def filter(self, **kw):
        return self


class _Union:
    def __init__(self, pagina):
        self.p = pagina

    @property
    def first(self):
        return self

    def wait_for(self, state, timeout):
        if not self.p.botones and not self.p.preguntas:
            raise PWTimeout("no aparece nada")


class _Pagina:
    def __init__(self, botones=(), preguntas=False, texto="Ya existe una declaracion original", falla_click=False):
        self.botones, self.preguntas, self.texto, self.falla_click = list(botones), preguntas, texto, falla_click
        self.clics = []

    def locator(self, selector):
        return _Botones(self) if selector == sel.AVISO_YA_DECLARADO else _Preguntas()

    def wait_for_load_state(self, *a, **k):
        pass


def test_con_el_aviso_se_pulsa_solo_rechazar_y_se_lanza_ya_declarado():
    p = _Pagina(botones=["Aceptar", "Rechazar"])
    with pytest.raises(AlreadyDeclared):
        dec.rechazar_si_ya_declarado(p)
    assert p.clics == ["Rechazar"]  # Aceptar seguiria adelante: nunca se pulsa


def test_si_aparecen_las_preguntas_no_se_hace_nada():
    p = _Pagina(preguntas=True)
    assert dec.rechazar_si_ya_declarado(p) is None and p.clics == []


def test_si_no_aparece_ni_el_aviso_ni_las_preguntas_no_decide_nada():
    p = _Pagina()
    assert dec.rechazar_si_ya_declarado(p, espera_ms=1) is None and p.clics == []


def test_sin_boton_rechazar_o_con_dos_no_se_pulsa_nada():
    for botones in (["Aceptar"], ["Aceptar", "Rechazar", "Rechazar"]):
        p = _Pagina(botones=botones)
        with pytest.raises(PortalChanged):
            dec.rechazar_si_ya_declarado(p)
        assert p.clics == []


def test_la_evidencia_se_toma_antes_de_pulsar_rechazar():
    orden = []
    p = _Pagina(botones=["Aceptar", "Rechazar"])
    p.clics = type("L", (), {"append": lambda self, x: orden.append(("clic", x))})()
    with pytest.raises(AlreadyDeclared):
        dec.rechazar_si_ya_declarado(p, evidencia=lambda: orden.append(("captura",)))
    assert orden == [("captura",), ("clic", "Rechazar")]


def test_si_falla_la_captura_o_el_clic_igual_se_declara_ya_declarado():
    with pytest.raises(AlreadyDeclared):
        dec.rechazar_si_ya_declarado(_Pagina(botones=["Rechazar"]), evidencia=lambda: 1 / 0)
    with pytest.raises(AlreadyDeclared):
        dec.rechazar_si_ya_declarado(_Pagina(botones=["Rechazar"], falla_click=True))


def test_el_unico_clic_de_la_funcion_es_sobre_rechazar():
    fuente = inspect.getsource(dec.rechazar_si_ya_declarado)
    assert fuente.count(".click()") == 1 and "rechazar.first.click()" in fuente


# ------------------------------------------------------------------ en los flujos: justo despues de Siguiente
def _con_orden(monkeypatch, modulo, nombres, orden, ya_declarado):
    for nombre in nombres:
        monkeypatch.setattr(modulo, nombre, lambda *a, _n=nombre, **k: orden.append(_n))

    def rechazar(*a, **k):
        orden.append("rechazar_si_ya_declarado")
        if ya_declarado:
            raise AlreadyDeclared("ya hay una declaracion")
    monkeypatch.setattr(dec, "rechazar_si_ya_declarado", rechazar)


@pytest.mark.parametrize("ya_declarado,esperado", [
    (False, ["siguiente", "rechazar_si_ya_declarado", "responder_valores_no", "siguiente_perfilador", "contador"]),
    (True, ["siguiente", "rechazar_si_ya_declarado"]),
])
def test_iva_revisa_el_aviso_justo_despues_de_siguiente_y_si_ya_esta_declarado_no_sigue(monkeypatch, ya_declarado, esperado):
    llamadas, orden = [], []
    _envio._preparar_flujo(monkeypatch, llamadas)
    _con_orden(monkeypatch, main.declaration, ("siguiente", "responder_valores_no", "siguiente_perfilador"), orden, ya_declarado)
    monkeypatch.setattr(main.signature, "llenar_contador", lambda *a, **k: orden.append("contador"))
    try:
        main._flujo(None, object(), "A1", PERIODO, "contador", object(), object(), enviar=True, ruc="1790000000001")
    except AlreadyDeclared:
        pass
    assert orden == esperado
    if ya_declarado:
        assert llamadas == []  # un fideicomiso ya declarado nunca llega al envio


@pytest.mark.parametrize("ya_declarado,esperado", [
    (False, ["siguiente", "rechazar_si_ya_declarado", "responder_no", "siguiente_perfilador"]),
    (True, ["siguiente", "rechazar_si_ya_declarado"]),
])
def test_retenciones_revisa_el_aviso_justo_despues_de_siguiente(monkeypatch, ya_declarado, esperado):
    orden = []
    monkeypatch.setattr(retenciones.authentication, "iniciar_sesion", lambda *a, **k: None)
    monkeypatch.setattr(retenciones, "abrir_formulario", lambda p: None)
    for nombre in ("seleccionar_obligacion", "seleccionar_periodo"):
        monkeypatch.setattr(retenciones.declaration, nombre, lambda *a, **k: None)
    _con_orden(monkeypatch, retenciones, ("siguiente", "responder_no", "siguiente_perfilador"), orden, False)

    def rechazar(*a, **k):
        orden.append("rechazar_si_ya_declarado")
        if ya_declarado:
            raise AlreadyDeclared("ya hay una declaracion")
    monkeypatch.setattr(retenciones.declaration, "rechazar_si_ya_declarado", rechazar)
    monkeypatch.setattr(retenciones, "capturar", lambda *a: None)
    try:
        retenciones.recorrer(None, object(), "A1", PERIODO, "firma", object(), object())
    except AlreadyDeclared:
        pass
    assert orden == esperado


# ------------------------------------------------------------------ en el lote: se sigue con el siguiente y se refleja en el Control
def _estados(tmp):
    con = sqlite3.connect(str(tmp / "execution_history.db"))
    try:
        return dict(con.execute("SELECT fideicomiso_id, estado FROM declaraciones").fetchall())
    finally:
        con.close()


def _lote_con_ya_declarado(entorno, monkeypatch, extra=(), impuesto=None):
    llamadas, tmp = entorno
    marcados = []
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr(main, "ruta_control", lambda: Path("control.xlsx"))
    monkeypatch.setattr(main, "marcar_declarado", lambda *a: marcados.append(a) or True)

    def flujo(ctx, page, cid, per, hasta, cred, cont, **kw):
        llamadas["flujo"].append(cid)
        if cid == "A2":
            raise AlreadyDeclared("ya hay una declaracion")
        return "comprobante serie 999" if kw.get("enviar") else None
    monkeypatch.setattr(main, "_flujo", flujo)
    monkeypatch.setattr(retenciones, "recorrer", flujo)
    argv = ["--lote", "--hasta", "contador", "--pausa", "0", *extra] + (["--impuesto", impuesto] if impuesto else [])
    return main.main(argv), llamadas, tmp, marcados


def test_un_fideicomiso_ya_declarado_no_detiene_el_lote_y_se_anota_en_el_control(entorno, monkeypatch):
    rc, llamadas, tmp, marcados = _lote_con_ya_declarado(entorno, monkeypatch)
    assert rc == 0 and llamadas["flujo"] == ["A1", "A2", "A3"]  # se siguio con el siguiente
    assert "error" not in llamadas["capturas"]  # el aviso ya tiene su captura: otra de error seria basura
    assert _estados(tmp) == {"A1": "simulado", "A2": "ya_declarado", "A3": "simulado"}
    assert [(m[1], m[2], m[3]) for m in marcados] == [(3, "A2", "declara_0")]  # solo el ya declarado (A1 y A3 son simulados)


def test_en_retenciones_se_anota_en_la_columna_de_retenciones(entorno, monkeypatch):
    rc, _, tmp, marcados = _lote_con_ya_declarado(entorno, monkeypatch, impuesto="1031")
    assert rc == 0 and [(m[2], m[3]) for m in marcados] == [("A2", "retencion_0")]


def test_un_envio_real_tambien_se_anota_como_declarado(entorno, monkeypatch):
    monkeypatch.setattr(settings, "DRY_RUN", False)
    respuestas = iter(["SI", "ENVIAR"])
    monkeypatch.setattr("builtins.input", lambda *_: next(respuestas))
    rc, _, tmp, marcados = _lote_con_ya_declarado(entorno, monkeypatch, extra=("--enviar", "--max", "1"))
    assert rc == 0 and _estados(tmp) == {"A1": "declarado"} and [(m[1], m[2]) for m in marcados] == [(2, "A1")]


def test_si_no_se_puede_escribir_el_control_el_lote_sigue(entorno, monkeypatch):
    llamadas, tmp = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr(main, "ruta_control", lambda: Path("control.xlsx"))

    def abierto(*a):
        raise ConfigError("El Control esta abierto en otro programa")
    monkeypatch.setattr(main, "marcar_declarado", abierto)

    def flujo(ctx, page, cid, per, hasta, cred, cont, **kw):
        llamadas["flujo"].append(cid)
        if cid == "A1":
            raise AlreadyDeclared("ya hay una declaracion")
    monkeypatch.setattr(main, "_flujo", flujo)
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0"]) == 0
    assert _estados(tmp) == {"A1": "ya_declarado", "A2": "simulado", "A3": "simulado"}


def test_sin_ruta_del_control_no_se_intenta_marcar(entorno, monkeypatch):
    llamadas, tmp = entorno
    marcados = []
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr(main, "marcar_declarado", lambda *a: marcados.append(a))
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: (_ for _ in ()).throw(AlreadyDeclared("ya")))
    main.main(["--lote", "--hasta", "contador", "--pausa", "0", "--max", "1"])
    assert marcados == [] and _estados(tmp) == {"A1": "ya_declarado"}


@pytest.mark.parametrize("estado,debe_avisar", [
    (Estado.DECLARADO, True), (Estado.YA_DECLARADO, True),
    (Estado.SIMULADO, False), (Estado.PARCIAL, False), (Estado.REVISION_MANUAL, False),
    (Estado.OBLIGACION_NO_DISPONIBLE, False), (Estado.ERROR, False),
])
def test_solo_los_estados_finales_de_declaracion_se_reflejan_en_el_control(estado, debe_avisar):
    avisos = []
    _avisar(lambda f, e: avisos.append((f, e)), "F", estado)
    assert bool(avisos) is debe_avisar


# ------------------------------------------------------------------ el lector del Control: DECLARADO es un valor valido
def test_declarado_se_omite_sin_contarlo_como_excluido(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fideicomisos"
    ws.append(["ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"])
    ws.append(["A", "a", "1790000000001", "DECLARADO", "SI", "x"])
    ws.append(["B", "b", "1790000000002", "SI", "Declarado", "x"])
    ws.append(["C", "c", "1790000000003", "X", "X", "x"])
    ruta = tmp_path / "c.xlsx"
    wb.save(ruta)
    iva, ret = leer_control(ruta, "declara_0"), leer_control(ruta, "retencion_0")
    assert [p.id for p in iva.pendientes] == ["B"] and [p.id for p in ret.pendientes] == ["A"]
    assert [e.id for e in iva.excluidos] == ["C"] and [e.id for e in ret.excluidos] == ["C"]  # solo lo realmente raro
    assert iva.omitidos == 1 and ret.omitidos == 1


def test_en_el_modo_individual_un_ya_declarado_tampoco_deja_captura_de_error(entorno, monkeypatch):
    from contextlib import contextmanager
    llamadas, _ = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr("builtins.input", lambda *_: "SI")

    @contextmanager
    def abrir():
        yield type("Ctx", (), {"pages": [], "new_page": lambda self: object()})()
    monkeypatch.setattr(main, "open_context", abrir)
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: (_ for _ in ()).throw(AlreadyDeclared("ya hay una declaracion")))
    argv = ["--contribuyente", "R1", "--login", "manual", "--credenciales", "consola", "--hasta", "siguiente"]
    assert main.main(argv) == 1  # el modo individual no tiene cola: termina con el aviso
    assert llamadas["capturas"] == []


def test_un_error_comun_si_deja_captura_de_error_en_el_modo_individual(entorno, monkeypatch):
    from contextlib import contextmanager
    llamadas, _ = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr("builtins.input", lambda *_: "SI")

    @contextmanager
    def abrir():
        yield type("Ctx", (), {"pages": [], "new_page": lambda self: object()})()
    monkeypatch.setattr(main, "open_context", abrir)
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: (_ for _ in ()).throw(PortalChanged("cambio el portal")))
    argv = ["--contribuyente", "R1", "--login", "manual", "--credenciales", "consola", "--hasta", "siguiente"]
    assert main.main(argv) == 1
    assert llamadas["capturas"] == ["error"]