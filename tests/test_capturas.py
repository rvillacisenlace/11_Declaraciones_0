import re
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import pytest

import main
from config import settings
from src.security.credential_repository import Credencial
from src.sri import retenciones, submission
from src.utils import evidence
from src.utils.exceptions import EnvioIncierto
from src.utils.rutas import carpeta_declaracion, carpeta_evidencia
from tests.test_submission import _enviar, _Pagina
from tests.test_verificacion import HOY, PERIODO, RUC


class _Ruta:
    name = "999_1790000000001_20261106143005.pdf"


# ------------------------------------------------------------------ evidence.capturar
class _PaginaFoto:
    def __init__(self):
        self.llamadas = []

    def screenshot(self, path, full_page):
        self.llamadas.append((path, full_page))
        Path(path).write_bytes(b"png")


def test_la_captura_va_a_la_carpeta_del_ruc_con_periodo_impuesto_y_paso(tmp_path):
    p = _PaginaFoto()
    ruta = evidence.capturar(p, tmp_path / "Resp" / RUC, (2026, 10), "02_preguntas", "1031")
    assert ruta.parent == tmp_path / "Resp" / RUC and ruta.exists() and p.llamadas[0][1] is True
    assert re.fullmatch(r"2026-10_1031_02_preguntas_\d{8}_\d{6}\.png", ruta.name)


def test_el_impuesto_por_defecto_es_iva(tmp_path):
    assert evidence.capturar(_PaginaFoto(), tmp_path, (2026, 10), "error").name.startswith("2026-10_2011_error_")


# ------------------------------------------------------------------ IVA: una captura por pantalla, justo antes de cada clic
def _preparar_iva(monkeypatch, pasos, envios):
    monkeypatch.setattr(main.authentication, "iniciar_sesion", lambda *a, **k: None)
    monkeypatch.setattr(main.navigation, "abrir_formulario_iva", lambda p: None)
    for nombre in ("seleccionar_obligacion", "seleccionar_periodo", "siguiente", "responder_valores_no", "siguiente_perfilador"):
        monkeypatch.setattr(main.declaration, nombre, lambda *a, **k: None)
    monkeypatch.setattr(main.signature, "llenar_contador", lambda *a, **k: None)
    monkeypatch.setattr(main.retenciones, "verificar_sin_recargos", lambda *a, **k: None)
    monkeypatch.setattr(main, "capturar", lambda page, carpeta, periodo, paso, impuesto: pasos.append((paso, impuesto, carpeta)))
    monkeypatch.setattr(submission, "enviar_declaracion", lambda *a, **k: envios.append((a, k)) or _Ruta())


def test_iva_toma_una_captura_por_pantalla_en_la_carpeta_del_responsable_y_el_ruc(monkeypatch):
    pasos = []
    _preparar_iva(monkeypatch, pasos, [])
    main._flujo(None, object(), "A1", PERIODO, "contador", object(), object(), ruc=RUC, responsable="Resp1")
    assert [p[0] for p in pasos] == ["01_periodo", "02_preguntas", "03_resumen"]
    assert all(p[1] == "2011" and p[2] == carpeta_evidencia("Resp1", RUC) for p in pasos)


@pytest.mark.parametrize("hasta,esperado", [
    ("periodo", ["01_periodo"]),
    ("siguiente", ["01_periodo"]),  # tras Siguiente la pantalla aun no tiene nada que registrar
    ("valores", ["01_periodo", "02_preguntas"]),
    ("firma", ["01_periodo", "02_preguntas"]),
    ("contador", ["01_periodo", "02_preguntas", "03_resumen"]),
])
def test_iva_no_captura_pantallas_sin_rellenar(monkeypatch, hasta, esperado):
    pasos = []
    _preparar_iva(monkeypatch, pasos, [])
    main._flujo(None, object(), "A1", PERIODO, hasta, object(), object(), ruc=RUC, responsable="Resp1")
    assert [p[0] for p in pasos] == esperado


def test_iva_sin_ruc_ni_responsable_usa_el_id_y_sin_responsable(monkeypatch):
    pasos = []
    _preparar_iva(monkeypatch, pasos, [])
    main._flujo(None, object(), "A1", PERIODO, "periodo", object(), object())
    assert pasos[0][2] == settings.EVIDENCE_DIR / "SIN RESPONSABLE" / "A1"


def test_iva_la_confirmacion_se_captura_con_el_callback_y_el_comprobante_va_al_arbol_del_responsable(monkeypatch):
    pasos, envios = [], []
    _preparar_iva(monkeypatch, pasos, envios)
    main._flujo(None, object(), "A1", PERIODO, "contador", object(), object(), enviar=True, ruc=RUC, responsable="Resp1")
    assert [p[0] for p in pasos] == ["01_periodo", "02_preguntas", "03_resumen"]  # la 04 la toma submission, no el flujo
    args, kw = envios[0]
    assert args[3] == carpeta_declaracion("Resp1", RUC, "2011")
    kw["evidencia"]()
    assert pasos[-1] == ("04_confirmacion", "2011", carpeta_evidencia("Resp1", RUC))


# ------------------------------------------------------------------ retenciones: lo mismo
def _preparar_ret(monkeypatch, pasos, envios):
    monkeypatch.setattr(retenciones.authentication, "iniciar_sesion", lambda *a, **k: None)
    monkeypatch.setattr(retenciones, "abrir_formulario", lambda p: None)
    for nombre in ("seleccionar_obligacion", "seleccionar_periodo"):
        monkeypatch.setattr(retenciones.declaration, nombre, lambda *a, **k: None)
    for nombre in ("siguiente", "responder_no", "siguiente_perfilador", "verificar_sin_recargos"):
        monkeypatch.setattr(retenciones, nombre, lambda *a, **k: None)
    monkeypatch.setattr(retenciones.signature, "llenar_contador", lambda *a, **k: None)
    monkeypatch.setattr(retenciones, "capturar", lambda page, carpeta, periodo, paso, impuesto: pasos.append((paso, impuesto, carpeta)))
    monkeypatch.setattr(retenciones.submission, "enviar_declaracion", lambda *a, **k: envios.append((a, k)) or _Ruta())


def test_retenciones_toma_una_captura_por_pantalla_en_la_carpeta_del_responsable_y_el_ruc(monkeypatch):
    pasos = []
    _preparar_ret(monkeypatch, pasos, [])
    retenciones.recorrer(None, object(), "A1", PERIODO, "contador", object(), object(), ruc=RUC, responsable="Resp1")
    assert [p[0] for p in pasos] == ["01_periodo", "02_preguntas", "03_resumen"]
    assert all(p[1] == "1031" and p[2] == carpeta_evidencia("Resp1", RUC) for p in pasos)


@pytest.mark.parametrize("hasta,esperado", [
    ("periodo", ["01_periodo"]), ("siguiente", ["01_periodo"]),
    ("valores", ["01_periodo", "02_preguntas"]), ("firma", ["01_periodo", "02_preguntas"]),
])
def test_retenciones_no_captura_pantallas_sin_rellenar(monkeypatch, hasta, esperado):
    pasos = []
    _preparar_ret(monkeypatch, pasos, [])
    retenciones.recorrer(None, object(), "A1", PERIODO, hasta, object(), object(), ruc=RUC, responsable="Resp1")
    assert [p[0] for p in pasos] == esperado


def test_retenciones_la_confirmacion_se_captura_con_el_callback(monkeypatch):
    pasos, envios = [], []
    _preparar_ret(monkeypatch, pasos, envios)
    retenciones.recorrer(None, object(), "A1", PERIODO, "contador", object(), object(), enviar=True, ruc=RUC, responsable="Resp1")
    args, kw = envios[0]
    assert args[3] == carpeta_declaracion("Resp1", RUC, "1031")
    kw["evidencia"]()
    assert pasos[-1] == ("04_confirmacion", "1031", carpeta_evidencia("Resp1", RUC))


# ------------------------------------------------------------------ submission: la captura va tras el exito y antes de Imprimir
def _con_callback(pagina, tmp_path, accion):
    return submission.enviar_declaracion(pagina, RUC, PERIODO, tmp_path / "ev", envio_autorizado=True, hoy=HOY,
                                         ahora=datetime(2026, 11, 6, 14, 30, 5), evidencia=accion)


def test_la_captura_de_confirmacion_ocurre_tras_el_exito_y_antes_de_imprimir(tmp_path):
    p = _Pagina()
    _con_callback(p, tmp_path, lambda: p.eventos.append(("captura",)))
    eventos = p.eventos
    i_exito = eventos.index(("espera", submission.MENSAJE_EXITO))
    i_foto = eventos.index(("captura",))
    i_imprimir = eventos.index(("clic", submission.BOTON_IMPRIMIR))
    assert i_exito < i_foto < i_imprimir


def test_si_la_captura_falla_el_comprobante_se_descarga_igual(tmp_path):
    def falla():
        raise RuntimeError("no se pudo capturar")
    p = _Pagina()
    ruta = _con_callback(p, tmp_path, falla)
    assert ruta.exists() and len(p.clics(submission.BOTON_IMPRIMIR)) == 1


def test_sin_confirmacion_del_portal_no_se_captura_nada(tmp_path):
    llamadas = []
    p = _Pagina(sin_aparecer=[submission.MENSAJE_EXITO])
    with pytest.raises(EnvioIncierto):
        _con_callback(p, tmp_path, lambda: llamadas.append(1))
    assert llamadas == []


def test_el_callback_es_opcional(tmp_path):
    assert _enviar(_Pagina(), tmp_path).exists()


# ------------------------------------------------------------------ main._datos_carpeta (modo individual)
def test_login_manual_no_tiene_datos_de_carpeta():
    args = Namespace(credenciales="consola", login="manual", contribuyente="R1", impuesto="2011")
    assert main._datos_carpeta(args, None) == (None, None)


def test_con_credenciales_por_consola_el_ruc_sale_de_la_credencial(monkeypatch):
    args = Namespace(credenciales="consola", login="auto", contribuyente="R1", impuesto="2011")
    assert main._datos_carpeta(args, Credencial("R1", "contribuyente", RUC, "x")) == (RUC, None)


@pytest.mark.parametrize("impuesto,marca", [("2011", "declara_0"), ("1031", "retencion_0")])
def test_con_el_excel_el_ruc_y_el_responsable_salen_del_control_segun_el_impuesto(monkeypatch, impuesto, marca):
    pedidos = []
    monkeypatch.setattr(main, "_fideicomiso", lambda cid, m: pedidos.append((cid, m)) or Namespace(ruc=RUC, responsable="Resp1"))
    args = Namespace(credenciales="excel", login="auto", contribuyente="142", impuesto=impuesto)
    assert main._datos_carpeta(args, object()) == (RUC, "Resp1")
    assert pedidos == [("142", marca)]