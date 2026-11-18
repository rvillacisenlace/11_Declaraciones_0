"""Con la sesion ya iniciada (segundo impuesto de un fideicomiso) no se vuelve a iniciar sesion, pero SI se vuelve a la
pagina del menu: la pantalla del formulario anterior no la trae."""
import logging

import pytest

import main
from src.sri import navigation, retenciones
from tests.test_capturas import _preparar_iva, _preparar_ret
from tests.test_verificacion import PERIODO, RUC


class _Pagina:
    def __init__(self, url="https://portal/inicio"):
        self.url = url
        self.goto_llamadas = []

    def goto(self, url, wait_until=None):
        self.goto_llamadas.append((url, wait_until))


@pytest.fixture(autouse=True)
def _inicio_limpio(monkeypatch):
    monkeypatch.setitem(navigation._INICIO, "url", None)


# ------------------------------------------------------------------ navigation
def test_recordar_inicio_guarda_la_url_actual():
    navigation.recordar_inicio(_Pagina("https://portal/menu"))
    assert navigation._INICIO["url"] == "https://portal/menu"


def test_volver_al_inicio_navega_a_la_pagina_recordada_sin_tocar_las_cookies():
    p = _Pagina("https://portal/formulario")
    navigation._INICIO["url"] = "https://portal/menu"
    navigation.volver_al_inicio(p)
    assert p.goto_llamadas == [("https://portal/menu", "domcontentloaded")]


def test_volver_al_inicio_sin_url_conocida_no_navega_y_lo_avisa(caplog):
    p = _Pagina()
    with caplog.at_level(logging.WARNING):
        navigation.volver_al_inicio(p)
    assert p.goto_llamadas == [] and "No se conoce la pagina de inicio" in caplog.text


# ------------------------------------------------------------------ IVA
def _orden_iva(monkeypatch, **kw):
    orden = []
    _preparar_iva(monkeypatch, [], [])
    monkeypatch.setattr(main.authentication, "iniciar_sesion", lambda *a, **k: orden.append("login"))
    monkeypatch.setattr(main.navigation, "volver_al_inicio", lambda p: orden.append("inicio"))
    monkeypatch.setattr(main.navigation, "abrir_formulario_iva", lambda p: orden.append("formulario"))
    main._flujo(None, object(), "A1", PERIODO, "periodo", object(), object(), ruc=RUC, responsable="R", **kw)
    return orden


def test_iva_con_sesion_nueva_inicia_sesion_y_no_vuelve_al_inicio(monkeypatch):
    assert _orden_iva(monkeypatch) == ["login", "formulario"]


def test_iva_con_sesion_reutilizada_vuelve_al_inicio_y_no_inicia_sesion(monkeypatch):
    assert _orden_iva(monkeypatch, sesion_iniciada=True) == ["inicio", "formulario"]


# ------------------------------------------------------------------ retenciones
def _orden_ret(monkeypatch, **kw):
    orden = []
    _preparar_ret(monkeypatch, [], [])
    monkeypatch.setattr(retenciones.authentication, "iniciar_sesion", lambda *a, **k: orden.append("login"))
    monkeypatch.setattr(retenciones.navigation, "volver_al_inicio", lambda p: orden.append("inicio"))
    monkeypatch.setattr(retenciones, "abrir_formulario", lambda p: orden.append("formulario"))
    retenciones.recorrer(None, object(), "A1", PERIODO, "periodo", object(), object(), ruc=RUC, responsable="R", **kw)
    return orden


def test_retenciones_con_sesion_nueva_inicia_sesion_y_no_vuelve_al_inicio(monkeypatch):
    assert _orden_ret(monkeypatch) == ["login", "formulario"]


def test_retenciones_con_sesion_reutilizada_vuelve_al_inicio_y_no_inicia_sesion(monkeypatch):
    assert _orden_ret(monkeypatch, sesion_iniciada=True) == ["inicio", "formulario"]


# ------------------------------------------------------------------ al abrir cada formulario se recuerda la pagina del menu
class _Elemento:
    def __init__(self):
        self.first = self

    def wait_for(self, **kw):
        pass

    def count(self):
        return 1

    def click(self):
        pass


class _PaginaConMenu(_Pagina):
    def get_by_text(self, *a, **k):
        return _Elemento()

    def locator(self, *a, **k):
        return _Elemento()


def test_abrir_el_formulario_de_iva_recuerda_la_pagina_del_menu():
    navigation.abrir_formulario_iva(_PaginaConMenu("https://portal/menu-iva"))
    assert navigation._INICIO["url"] == "https://portal/menu-iva"


def test_abrir_el_formulario_de_retenciones_recuerda_la_pagina_del_menu():
    retenciones.abrir_formulario(_PaginaConMenu("https://portal/menu-ret"))
    assert navigation._INICIO["url"] == "https://portal/menu-ret"
