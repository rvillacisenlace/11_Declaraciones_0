import pytest
from openpyxl import Workbook

import main
from config import settings
from src.utils.exceptions import ConfigError
from tests.test_credentials import ACCESOS, CLAVE_LIBRO, CONTADOR, _xlsx_cifrado


def _control(tmp_path, filas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fideicomisos"
    ws.append(["ID", "NOMBRE", "RUC", "DECLARA_0", "RESPONSABLE"])
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def _preparar(tmp_path, monkeypatch, filas_control, contador=CONTADOR):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", _xlsx_cifrado(tmp_path, ACCESOS, contador))
    monkeypatch.setenv("CONTROL_XLSX", str(_control(tmp_path, filas_control)))


def test_login_auto_cruza_por_ruc_no_por_id(tmp_path, monkeypatch):
    # ID 8 del Control apunta al RUC ...001; el ID 8 de Accesos pertenece a ...002: debe ganar el RUC
    _preparar(tmp_path, monkeypatch, [["8", "F", "1790000000001", "SI", "x"]])
    cred, contador = main._cargar_credenciales("8", "auto", True, CLAVE_LIBRO)
    assert cred.ruc == "1790000000001" and cred.clave == "clave-uno" and contador.tipo == "contador"


def test_login_manual_solo_carga_el_contador(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, [])
    cred, contador = main._cargar_credenciales("8", "manual", True, CLAVE_LIBRO)
    assert cred is None and contador.ruc == "1710000000001"


def test_sin_contador_no_lo_pide(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, [["8", "F", "1790000000001", "SI", "x"]], contador=None)
    cred, contador = main._cargar_credenciales("8", "auto", False, CLAVE_LIBRO)
    assert cred is not None and contador is None


def test_no_marcado_con_si_no_se_procesa(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, [["8", "F", "1790000000001", "NO", "x"]])
    with pytest.raises(ConfigError, match="no esta marcado con SI"):
        main._cargar_credenciales("8", "auto", False, CLAVE_LIBRO)


def test_excluido_por_datos_se_informa_el_motivo(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, [["8", "F", "1790000000001", "SI", "x"],
                                      ["9", "G", "1790000000001", "NO", "x"]])  # RUC repetido
    with pytest.raises(ConfigError, match="RUC repetido"):
        main._cargar_credenciales("8", "auto", False, CLAVE_LIBRO)


def test_id_inexistente(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch, [["8", "F", "1790000000001", "SI", "x"]])
    with pytest.raises(ConfigError, match="no esta marcado con SI"):
        main._cargar_credenciales("999", "auto", False, CLAVE_LIBRO)
