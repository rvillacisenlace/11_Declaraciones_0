import io

import msoffcrypto
from msoffcrypto.format.ooxml import OOXMLFile
import pytest
from openpyxl import Workbook

from config import settings
from src.security import credential_repository as repo
from src.utils.exceptions import ConfigError

CLAVE_LIBRO = "maestra-de-prueba"


def _xlsx_cifrado(tmp_path, filas, hoja="Credenciales", password=CLAVE_LIBRO):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(["id", "tipo", "ruc", "clave", "contador_id"])
    for f in filas:
        ws.append(f)
    plano = io.BytesIO()
    wb.save(plano)
    plano.seek(0)
    ruta = tmp_path / "cred.xlsx"
    with open(ruta, "wb") as salida:
        OOXMLFile(plano).encrypt(password, salida)
    return ruta


FILAS = [["C001", "contribuyente", "1790000000001", "clave-fake", "K01"],
         ["K01", "contador", "1710000000001", "clave-contador", None]]


def test_lee_credencial_y_oculta_clave(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", _xlsx_cifrado(tmp_path, FILAS))
    c = repo.cargar("C001", CLAVE_LIBRO)
    assert c.ruc == "1790000000001" and c.clave == "clave-fake" and c.contador_id == "K01"
    assert "clave-fake" not in repr(c) and "clave-fake" not in str(c)
    assert "1790000000001" not in str(c)


def test_password_incorrecta(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", _xlsx_cifrado(tmp_path, FILAS))
    with pytest.raises(ConfigError):
        repo.cargar("C001", "otra")


def test_id_inexistente_o_duplicado(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", _xlsx_cifrado(tmp_path, FILAS + [FILAS[0]]))
    with pytest.raises(ConfigError):
        repo.cargar("C001", CLAVE_LIBRO)  # duplicado
    with pytest.raises(ConfigError):
        repo.cargar("NOEXISTE", CLAVE_LIBRO)


def test_archivo_sin_cifrar_se_rechaza(tmp_path, monkeypatch):
    wb = Workbook()
    wb.active.title = "Credenciales"
    ruta = tmp_path / "plano.xlsx"
    wb.save(ruta)
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", ruta)
    with pytest.raises(ConfigError):
        repo.cargar("C001", CLAVE_LIBRO)


def test_sin_ruta_configurada(monkeypatch):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", None)
    with pytest.raises(ConfigError):
        repo.cargar("C001", CLAVE_LIBRO)
