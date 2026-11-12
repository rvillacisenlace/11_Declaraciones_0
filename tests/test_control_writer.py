import os
import zipfile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table

from src.services import control_writer as cw
from src.utils.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _sin_respaldos_previos():
    cw._RESPALDADOS.clear()


def _control(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fideicomisos"
    ws.append(["ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"])
    ws.append(["A1", "uno", "1790000000001", "SI", "NO", "Ana"])
    ws.append(["A2", "dos", "1790000000002", "NO", "SI", "Luis"])
    ws.append(["A3", "tres", "1790000000003", "SI", "SI", "Ana"])
    ws["G2"] = '=A2&"x"'  # una formula en otra celda
    ws["D2"].fill = PatternFill("solid", fgColor="FFFF00")
    dv = DataValidation(type="list", formula1='"SI;NO;DECLARADO"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("D2:E4")
    ws.add_table(Table(displayName="TablaControl", ref="A1:F4"))
    wb.create_sheet("Seguimiento").append(["X", "=1+1"])
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def _marcar(ruta, tmp_path, fila, id_, marca):
    return cw.marcar_declarado(ruta, fila, id_, marca, tmp_path / "resp")


def test_marca_solo_la_celda_pedida(tmp_path):
    ruta = _control(tmp_path)
    antes = cw._valores(ruta)
    assert _marcar(ruta, tmp_path, 2, "A1", "declara_0") is True
    despues = cw._valores(ruta)
    esperado = {h: [list(f) for f in filas] for h, filas in antes.items()}
    esperado["Fideicomisos"][1][3] = "DECLARADO"
    assert {h: [list(f) for f in filas] for h, filas in despues.items()} == esperado


def test_cada_impuesto_marca_su_propia_columna(tmp_path):
    ruta = _control(tmp_path)
    assert _marcar(ruta, tmp_path, 4, "A3", "retencion_0") is True
    fila = cw._valores(ruta)["Fideicomisos"][3]
    assert fila[3] == "SI" and fila[4] == "DECLARADO"


def test_el_resto_del_archivo_queda_identico(tmp_path):
    ruta = _control(tmp_path)
    original = tmp_path / "original.xlsx"
    original.write_bytes(ruta.read_bytes())
    _marcar(ruta, tmp_path, 2, "A1", "declara_0")
    zo, zn = zipfile.ZipFile(original), zipfile.ZipFile(ruta)
    assert zo.namelist() == zn.namelist()
    assert [n for n in zo.namelist() if zo.read(n) != zn.read(n)] == ["xl/worksheets/sheet1.xml"]
    wb = load_workbook(ruta)  # el resultado es un libro valido y conserva formula, validacion, tabla y formato
    ws = wb["Fideicomisos"]
    assert ws["G2"].value == '=A2&"x"' and wb["Seguimiento"]["B1"].value == "=1+1"
    assert ws.data_validations.dataValidation[0].formula1 == '"SI;NO;DECLARADO"'
    assert "TablaControl" in ws.tables and ws["D2"].fill.fgColor.rgb.endswith("FFFF00")


def test_si_ya_dice_declarado_no_cambia_nada(tmp_path):
    ruta = _control(tmp_path)
    _marcar(ruta, tmp_path, 2, "A1", "declara_0")
    antes = ruta.read_bytes()
    assert _marcar(ruta, tmp_path, 2, "A1", "declara_0") is True
    assert ruta.read_bytes() == antes


@pytest.mark.parametrize("fila,id_,marca", [
    (3, "A2", "declara_0"),   # la celda dice NO: nunca se pisa otro valor
    (2, "A9", "declara_0"),   # el ID de esa fila es otro (el Control cambio)
    (99, "A1", "declara_0"),  # la fila ya no existe
])
def test_no_toca_lo_que_no_es_un_si_de_ese_id(tmp_path, fila, id_, marca):
    ruta = _control(tmp_path)
    antes = ruta.read_bytes()
    assert _marcar(ruta, tmp_path, fila, id_, marca) is False
    assert ruta.read_bytes() == antes


def test_hace_una_sola_copia_de_seguridad_con_el_contenido_original(tmp_path):
    ruta = _control(tmp_path)
    original = ruta.read_bytes()
    _marcar(ruta, tmp_path, 2, "A1", "declara_0")
    _marcar(ruta, tmp_path, 4, "A3", "declara_0")
    copias = list((tmp_path / "resp").iterdir())
    assert len(copias) == 1 and copias[0].read_bytes() == original


def test_si_el_control_esta_abierto_en_excel_no_se_pierde_nada(tmp_path, monkeypatch):
    ruta = _control(tmp_path)
    antes = ruta.read_bytes()

    def bloqueado(*a, **k):
        raise PermissionError("en uso")
    monkeypatch.setattr(os, "replace", bloqueado)
    with pytest.raises(ConfigError, match="abierto"):
        _marcar(ruta, tmp_path, 2, "A1", "declara_0")
    assert ruta.read_bytes() == antes and list(tmp_path.glob("~zero_*")) == []


def test_si_la_verificacion_falla_no_se_reemplaza_el_archivo(tmp_path, monkeypatch):
    ruta = _control(tmp_path)
    antes = ruta.read_bytes()

    def falla(*a, **k):
        raise ConfigError("no coincide")
    monkeypatch.setattr(cw, "_verificar", falla)
    with pytest.raises(ConfigError):
        _marcar(ruta, tmp_path, 2, "A1", "declara_0")
    assert ruta.read_bytes() == antes and list(tmp_path.glob("~zero_*")) == []


def test_errores_de_entrada(tmp_path):
    ruta = _control(tmp_path)
    with pytest.raises(ConfigError, match="Marca desconocida"):
        _marcar(ruta, tmp_path, 2, "A1", "otra")
    with pytest.raises(ConfigError, match="No se encontro"):
        cw.marcar_declarado(None, 2, "A1", "declara_0")
    with pytest.raises(ConfigError, match="No se encontro"):
        cw.marcar_declarado(tmp_path / "no_existe.xlsx", 2, "A1", "declara_0")