import pytest

from config import settings
from src.utils.exceptions import ConfigError
from src.utils.rutas import carpeta_declaracion


def test_arbol_de_declaraciones(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path / "Declaraciones")
    base = tmp_path / "Declaraciones" / "1790000000001"
    assert carpeta_declaracion("1790000000001", "2011") == base / "2011 - Declaraci\u00f3n de IVA"
    assert carpeta_declaracion("1790000000001", "1031") == base / "1031 - Declaraci\u00f3n de retenciones en la fuente"


def test_impuesto_desconocido(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path)
    with pytest.raises(ConfigError, match="desconocido"):
        carpeta_declaracion("1790000000001", "9999")