import pytest

import main
from src.utils.exceptions import ConfigError


def _teclado(monkeypatch, ruc="1710000000001", clave="clave-fake"):
    monkeypatch.setattr("builtins.input", lambda *_: ruc)
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: clave)


def test_login_manual_sin_contador_no_pide_nada(monkeypatch):
    def no_debe_pedir(*_):
        raise AssertionError("no debia pedir datos")
    monkeypatch.setattr("builtins.input", no_debe_pedir)
    monkeypatch.setattr(main.getpass, "getpass", no_debe_pedir)
    assert main._credenciales_por_consola("C001", "manual", False) == (None, None)


def test_pide_solo_el_contador_con_login_manual(monkeypatch):
    _teclado(monkeypatch)
    cred, contador = main._credenciales_por_consola("C001", "manual", True)
    assert cred is None and contador.tipo == "contador" and contador.ruc == "1710000000001"
    assert "clave-fake" not in repr(contador) and "clave-fake" not in str(contador)


def test_login_auto_pide_el_contribuyente(monkeypatch):
    _teclado(monkeypatch, ruc="1790000000001")
    cred, contador = main._credenciales_por_consola("C001", "auto", False)
    assert cred.id == "C001" and cred.tipo == "contribuyente" and contador is None


def test_ruc_de_contador_invalido(monkeypatch):
    _teclado(monkeypatch, ruc="123")
    with pytest.raises(ConfigError):
        main._credenciales_por_consola("C001", "manual", True)


def test_clave_vacia(monkeypatch):
    _teclado(monkeypatch, clave="")
    with pytest.raises(ConfigError):
        main._credenciales_por_consola("C001", "manual", True)