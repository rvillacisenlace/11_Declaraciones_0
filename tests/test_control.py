import pytest
from openpyxl import Workbook

from src.services.fideicomiso_service import leer_control
from src.utils.exceptions import ConfigError

ENC = ["ID", "NOMBRE", "RUC", "DECLARA_0", "RESPONSABLE"]


def _libro(tmp_path, filas, hoja="Fideicomisos", enc=ENC):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(enc)
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def test_selecciona_solo_los_validos(tmp_path):
    r = leer_control(_libro(tmp_path, [
        ["F1", "Uno", "1790000000001", "SI", "A"],
        ["F2", "Dos", "1790000000002", "no", "A"],
        ["F3", "Tres", "1790000000003", "", "A"],
        ["F4", "Cuatro", "1790000000004", "Sí", "B"],
    ]))
    assert [p.id for p in r.pendientes] == ["F1", "F4"]
    assert r.omitidos == 2 and not r.excluidos and r.total == 4


def test_excluye_id_vacio_y_repetido(tmp_path):
    r = leer_control(_libro(tmp_path, [
        ["", "A", "1790000000001", "SI", "x"],
        ["F2", "B", "1790000000002", "SI", "x"],
        ["F2", "C", "1790000000003", "NO", "x"],
    ]))
    motivos = {e.fila: e.motivo for e in r.excluidos}
    assert "ID vacio" in motivos[2] and "ID repetido" in motivos[3] and not r.pendientes


def test_excluye_ruc_invalido_y_repetido(tmp_path):
    r = leer_control(_libro(tmp_path, [
        ["F1", "A", "17900000001", "SI", "x"],
        ["F2", "B", "1790000000002", "SI", "x"],
        ["F3", "C", "1790000000002", "NO", "x"],
        ["F4", "D", 190000000001, "SI", "x"],  # numero sin cero inicial: no se adivina
    ]))
    motivos = {e.id: e.motivo for e in r.excluidos}
    assert "RUC invalido" in motivos["F1"] and "RUC repetido" in motivos["F2"] and "RUC invalido" in motivos["F4"]
    assert not r.pendientes


def test_valor_desconocido_en_declara_0(tmp_path):
    r = leer_control(_libro(tmp_path, [["F1", "A", "1790000000001", "X", "x"]]))
    assert "no reconocido" in r.excluidos[0].motivo


def test_encabezados_con_otras_mayusculas_y_orden(tmp_path):
    r = leer_control(_libro(tmp_path, [["1790000000001", "F1", "SI", "x", "A"]],
                            enc=["ruc", "Id", "Declara_0", "Nombre", "Responsable"]))
    assert r.pendientes[0].id == "F1" and r.pendientes[0].ruc == "1790000000001"


def test_ignora_filas_vacias(tmp_path):
    r = leer_control(_libro(tmp_path, [[None] * 5, ["F1", "A", "1790000000001", "SI", "x"], [None] * 5]))
    assert r.total == 1 and len(r.pendientes) == 1


def test_errores_de_estructura(tmp_path):
    with pytest.raises(ConfigError):
        leer_control(tmp_path / "no_existe.xlsx")
    with pytest.raises(ConfigError):
        leer_control(_libro(tmp_path, [], hoja="Otra"))
    with pytest.raises(ConfigError):
        leer_control(_libro(tmp_path, [], enc=["ID", "NOMBRE", "RUC"]))
