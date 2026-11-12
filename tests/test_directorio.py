import pytest
from openpyxl import Workbook

from src.services.fideicomiso_service import leer_directorio
from src.utils.exceptions import ConfigError


def _control(tmp_path, filas, encabezado=("ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"), hoja="Fideicomisos"):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(list(encabezado))
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def test_lee_todas_las_filas_sin_importar_las_marcas(tmp_path):
    ruta = _control(tmp_path, [["1", "a", "1790000000001", "NO", "NO", "Ana"], ["2", "b", "1790000000002", "SI", "SI", "Luis"],
                               ["3", "c", "1790000000003", None, None, None]])
    d = leer_directorio(ruta)
    assert d.por_id == {"1": ("1790000000001", "Ana"), "2": ("1790000000002", "Luis"), "3": ("1790000000003", "")}
    assert d.por_ruc["1790000000002"] == "Luis" and d.ambiguos == []


def test_una_fila_repetida_con_los_mismos_datos_no_es_ambigua(tmp_path):
    ruta = _control(tmp_path, [["1", "a", "1790000000001", "NO", "NO", "Ana"], ["1", "a", "1790000000001", "NO", "NO", "Ana"]])
    d = leer_directorio(ruta)
    assert d.por_id == {"1": ("1790000000001", "Ana")} and d.ambiguos == []


def test_un_ruc_con_dos_responsables_es_ambiguo_y_no_se_usa(tmp_path):
    ruta = _control(tmp_path, [["1", "a", "1790000000001", "NO", "NO", "Ana"], ["2", "b", "1790000000001", "NO", "NO", "Luis"]])
    d = leer_directorio(ruta)
    assert "1790000000001" in d.ambiguos and "1790000000001" not in d.por_ruc
    assert d.por_id == {"1": ("1790000000001", "Ana"), "2": ("1790000000001", "Luis")}  # los IDs si son distintos


def test_un_id_con_dos_datos_distintos_es_ambiguo_y_no_se_usa(tmp_path):
    ruta = _control(tmp_path, [["1", "a", "1790000000001", "NO", "NO", "Ana"], ["1", "b", "1790000000002", "NO", "NO", "Ana"]])
    d = leer_directorio(ruta)
    assert "1" in d.ambiguos and "1" not in d.por_id


def test_las_filas_totalmente_vacias_se_ignoran(tmp_path):
    ruta = _control(tmp_path, [[None, None, None, None, None, "Ana"], ["1", "a", "1790000000001", "NO", "NO", "Ana"]])
    assert list(leer_directorio(ruta).por_id) == ["1"]


def test_errores_de_estructura(tmp_path):
    with pytest.raises(ConfigError, match="CONTROL_XLSX"):
        leer_directorio(None)
    with pytest.raises(ConfigError, match="No se encontro"):
        leer_directorio(tmp_path / "no_existe.xlsx")
    with pytest.raises(ConfigError, match="Falta la hoja"):
        leer_directorio(_control(tmp_path, [], hoja="Otra"))
    with pytest.raises(ConfigError, match="Faltan columnas.*responsable"):
        leer_directorio(_control(tmp_path, [], encabezado=("ID", "RUC")))