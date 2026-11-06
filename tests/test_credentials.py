import io

import pytest
from msoffcrypto.format.ooxml import OOXMLFile
from openpyxl import Workbook

from config import settings
from src.security import credential_repository as repo
from src.utils.exceptions import ConfigError

CLAVE_LIBRO = "maestra-de-prueba"
ENC_ACCESOS = ["ID fideicomiso", "Usuario SRI", "Contraseña SRI", "Correo"]


def _xlsx_cifrado(tmp_path, accesos, contador=None, password=CLAVE_LIBRO, hoja_accesos="Accesos"):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja_accesos
    ws.append(ENC_ACCESOS)
    for f in accesos:
        ws.append(f)
    if contador is not None:
        wc = wb.create_sheet("Contador")
        wc.append(["Usuario SRI", "Contraseña SRI"])
        for f in contador:
            wc.append(f)
    plano = io.BytesIO()
    wb.save(plano)
    plano.seek(0)
    ruta = tmp_path / "cred.xlsx"
    with open(ruta, "wb") as salida:
        OOXMLFile(plano).encrypt(password, salida)
    return ruta


ACCESOS = [[7, "1790000000001", "clave-uno", None],
           [8, "1790000000002", "clave-dos", None]]
CONTADOR = [["1710000000001", "clave-contador"]]


def _usar(monkeypatch, ruta):
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", ruta)


def test_lee_contribuyente_por_ruc_y_oculta_clave(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS))
    c = repo.cargar_contribuyente("162", "1790000000002", CLAVE_LIBRO)
    assert c.id == "162" and c.ruc == "1790000000002" and c.clave == "clave-dos"
    assert "clave-dos" not in repr(c) and "clave-dos" not in str(c) and "1790000000002" not in str(c)


def test_el_id_del_acceso_no_se_usa_para_cruzar(tmp_path, monkeypatch):
    # el ID 7 de Accesos pertenece al RUC ...001; pedir otro RUC debe devolver SU clave, no la de la fila 7
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS))
    assert repo.cargar_contribuyente("7", "1790000000002", CLAVE_LIBRO).clave == "clave-dos"


def test_password_incorrecta(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS))
    with pytest.raises(ConfigError):
        repo.cargar_contribuyente("1", "1790000000001", "otra")


def test_sin_credencial_para_el_ruc(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS))
    with pytest.raises(ConfigError, match="No hay credencial"):
        repo.cargar_contribuyente("1", "1790000000999", CLAVE_LIBRO)


def test_filas_duplicadas_con_la_misma_clave_se_aceptan(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS + [[9, "1790000000001", "clave-uno", None]]))
    assert repo.cargar_contribuyente("1", "1790000000001", CLAVE_LIBRO).clave == "clave-uno"


def test_filas_duplicadas_con_claves_distintas_son_ambiguas(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS + [[9, "1790000000001", "otra-clave", None]]))
    with pytest.raises(ConfigError, match="ambigua"):
        repo.cargar_contribuyente("1", "1790000000001", CLAVE_LIBRO)


def test_credencial_sin_clave(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, [[1, "1790000000001", None, None]]))
    with pytest.raises(ConfigError, match="no tiene clave"):
        repo.cargar_contribuyente("1", "1790000000001", CLAVE_LIBRO)


def test_archivo_sin_cifrar_se_rechaza(tmp_path, monkeypatch):
    wb = Workbook()
    wb.active.title = "Accesos"
    ruta = tmp_path / "plano.xlsx"
    wb.save(ruta)
    _usar(monkeypatch, ruta)
    with pytest.raises(ConfigError):
        repo.cargar_contribuyente("1", "1790000000001", CLAVE_LIBRO)


def test_sin_ruta_configurada(monkeypatch):
    _usar(monkeypatch, None)
    with pytest.raises(ConfigError):
        repo.cargar_contador(CLAVE_LIBRO)


def test_contador_unico(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS, CONTADOR))
    c = repo.cargar_contador(CLAVE_LIBRO)
    assert c.tipo == "contador" and c.ruc == "1710000000001" and c.clave == "clave-contador"
    assert "clave-contador" not in repr(c)


def test_contador_debe_ser_exactamente_una_fila(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS, []))
    with pytest.raises(ConfigError, match="exactamente 1"):
        repo.cargar_contador(CLAVE_LIBRO)
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS, CONTADOR + [["1710000000002", "x"]]))
    with pytest.raises(ConfigError, match="exactamente 1"):
        repo.cargar_contador(CLAVE_LIBRO)


def test_contador_sin_hoja_o_con_ruc_invalido(tmp_path, monkeypatch):
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS))  # sin hoja Contador
    with pytest.raises(ConfigError, match="Falta la hoja"):
        repo.cargar_contador(CLAVE_LIBRO)
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, ACCESOS, [["123", "x"]]))
    with pytest.raises(ConfigError, match="13 digitos"):
        repo.cargar_contador(CLAVE_LIBRO)


def test_auditar_reporta_motivos_sin_claves(tmp_path, monkeypatch):
    filas = ACCESOS + [[9, "1790000000003", None, None],
                       [10, "1790000000004", "a", None], [11, "1790000000004", "b", None]]
    _usar(monkeypatch, _xlsx_cifrado(tmp_path, filas))
    p = repo.auditar(["1790000000001", "1790000000003", "1790000000004", "1790000000999"], CLAVE_LIBRO)
    assert "1790000000001" not in p
    assert "sin clave" in p["1790000000003"] and "ambigua" in p["1790000000004"] and "sin credencial" in p["1790000000999"]
    assert "clave" not in "".join(p.values()).replace("sin clave", "").replace("claves distintas", "")
