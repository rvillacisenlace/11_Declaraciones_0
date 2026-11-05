import pytest

from config import settings
from main import _cargar_credenciales
from src.utils.exceptions import ConfigError
from tests.test_credentials import CLAVE_LIBRO, FILAS, _xlsx_cifrado


def _usar(tmp_path, monkeypatch, filas):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", _xlsx_cifrado(tmp_path, filas))


def test_login_manual_con_contador(tmp_path, monkeypatch):
    _usar(tmp_path, monkeypatch, FILAS)
    cred, contador = _cargar_credenciales("C001", "manual", True, CLAVE_LIBRO)
    assert cred is None and contador.id == "K01" and contador.tipo == "contador"


def test_login_auto_sin_contador(tmp_path, monkeypatch):
    _usar(tmp_path, monkeypatch, FILAS)
    cred, contador = _cargar_credenciales("C001", "auto", False, CLAVE_LIBRO)
    assert cred.id == "C001" and contador is None


def test_contribuyente_sin_contador_asignado(tmp_path, monkeypatch):
    _usar(tmp_path, monkeypatch, [["C001", "contribuyente", "1790000000001", "x", None]])
    with pytest.raises(ConfigError):
        _cargar_credenciales("C001", "manual", True, CLAVE_LIBRO)


def test_la_fila_asignada_no_es_contador(tmp_path, monkeypatch):
    filas = [["C001", "contribuyente", "1790000000001", "x", "C002"],
             ["C002", "contribuyente", "1790000000002", "y", None]]
    _usar(tmp_path, monkeypatch, filas)
    with pytest.raises(ConfigError):
        _cargar_credenciales("C001", "manual", True, CLAVE_LIBRO)
