import builtins
import sys

import pytest

import main as zero_main
import zero_app


def test_devuelve_el_codigo_de_main(monkeypatch):
    monkeypatch.setattr(zero_main, "main", lambda argv=None: 3)
    assert zero_app.ejecutar() == 3


def test_un_error_inesperado_se_muestra_y_devuelve_2(monkeypatch, capsys):
    def revienta(argv=None):
        raise ValueError("detalle-visible")
    monkeypatch.setattr(zero_main, "main", revienta)
    assert zero_app.ejecutar() == 2
    salida = capsys.readouterr()
    assert "ERROR INESPERADO" in salida.out and "detalle-visible" in salida.err


@pytest.mark.parametrize("codigo,esperado", [(2, 2), (None, 0), ("mensaje", 1)])
def test_systemexit_se_convierte_en_codigo(monkeypatch, codigo, esperado):
    def sale(argv=None):
        raise SystemExit(codigo)
    monkeypatch.setattr(zero_main, "main", sale)
    assert zero_app.ejecutar() == esperado


def test_en_desarrollo_no_pide_enter(monkeypatch):
    monkeypatch.setattr(zero_app, "ejecutar", lambda: 0)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(builtins, "input", lambda *a: pytest.fail("no debio pedir ENTER"))
    assert zero_app.principal() == 0


def test_en_el_exe_espera_enter_para_que_se_lea_el_resultado(monkeypatch):
    pedidos = []
    monkeypatch.setattr(zero_app, "ejecutar", lambda: 1)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(builtins, "input", lambda *a: pedidos.append(a) or "")
    assert zero_app.principal() == 1 and len(pedidos) == 1


def test_en_el_exe_sin_consola_no_se_cuelga(monkeypatch):
    monkeypatch.setattr(zero_app, "ejecutar", lambda: 0)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def sin_entrada(*a):
        raise EOFError
    monkeypatch.setattr(builtins, "input", sin_entrada)
    assert zero_app.principal() == 0
