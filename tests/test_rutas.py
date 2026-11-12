import pytest

from config import settings
from src.utils.exceptions import ConfigError
from src.utils.rutas import SIN_RESPONSABLE, carpeta_declaracion, carpeta_evidencia, nombre_carpeta

RUC = "1790000000001"
P = (2026, 10)


def test_arbol_de_declaraciones_por_responsable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path / "Declaraciones")
    base = tmp_path / "Declaraciones" / "Justin" / RUC / "10-2026"
    assert carpeta_declaracion("Justin", RUC, "2011", P) == base / "2011 - Declaraci\u00f3n de IVA"
    assert carpeta_declaracion("Justin", RUC, "1031", P) == base / "1031 - Declaraci\u00f3n de retenciones en la fuente"


def test_arbol_de_evidencias_por_responsable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EVIDENCE_DIR", tmp_path / "Evidencias")
    assert carpeta_evidencia("Justin", RUC) == tmp_path / "Evidencias" / "Justin" / RUC


def test_impuesto_desconocido(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path)
    with pytest.raises(ConfigError, match="desconocido"):
        carpeta_declaracion("Justin", RUC, "9999", P)


@pytest.mark.parametrize("texto,esperado", [
    ("Justin", "Justin"),
    ("  Mar\u00eda   P\u00e9rez  ", "Mar\u00eda P\u00e9rez"),  # espacios repetidos y acentos se conservan
    ("Ana/Luz", "Ana_Luz"),
    ('a<b>c:d"e|f?g*h', "a_b_c_d_e_f_g_h"),
    ("Juan.", "Juan"),  # Windows no admite punto ni espacio final
    ("CON", "CON_"), ("lpt1", "lpt1_"),  # nombres reservados de Windows
])
def test_nombre_de_carpeta_valido_en_windows(texto, esperado):
    assert nombre_carpeta(texto) == esperado


@pytest.mark.parametrize("texto", [None, "", "   ", "..", "...", "///", "\\\\"])
def test_vacio_o_sin_nada_util_va_a_sin_responsable(texto):
    assert nombre_carpeta(texto) == SIN_RESPONSABLE


@pytest.mark.parametrize("malicioso", ["../../Windows", "..\\..\\x", "C:\\Windows", "a/../../b"])
def test_un_responsable_nunca_puede_salirse_de_su_nivel(tmp_path, monkeypatch, malicioso):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path / "D")
    ruta = carpeta_declaracion(malicioso, RUC, "2011", P)
    assert (tmp_path / "D") in ruta.parents and ruta.parent.parent.parent.parent == tmp_path / "D"  # un solo nivel de responsable
    assert ".." not in ruta.parts


def test_nombre_largo_se_recorta():
    assert len(nombre_carpeta("x" * 200)) == 60


def test_sin_ruc_se_usa_un_nombre_claro(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EVIDENCE_DIR", tmp_path)
    assert carpeta_evidencia("Justin", "") == tmp_path / "Justin" / "SIN RUC"


@pytest.mark.parametrize("periodo,esperado", [((2026, 10), "10-2026"), ((2027, 1), "01-2027"), ((2026, 12), "12-2026")])
def test_el_periodo_va_como_mes_guion_anio(tmp_path, monkeypatch, periodo, esperado):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path)
    ruta = carpeta_declaracion("Justin", RUC, "2011", periodo)
    assert ruta.parent.name == esperado and ruta.parent.parent.name == RUC  # Responsable/RUC/MM-AAAA/impuesto


def test_cada_periodo_tiene_su_propia_carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path)
    assert carpeta_declaracion("Justin", RUC, "2011", (2026, 10)) != carpeta_declaracion("Justin", RUC, "2011", (2026, 11))
    assert carpeta_declaracion("Justin", RUC, "2011", (2026, 10)) != carpeta_declaracion("Justin", RUC, "2011", (2027, 10))
