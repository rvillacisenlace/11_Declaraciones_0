from diagnostics import mover_comprobantes as mv
from config import settings
from tests.test_verificacion import LINEAS, RUC, _pdf_minimo

NOMBRE = f"111111111111_{RUC}_20261106143005.pdf"


def _preparar(tmp_path, monkeypatch):
    origen = tmp_path / "evidence"
    (origen / "142" / "2026-10").mkdir(parents=True)
    (origen / "142" / "2026-10" / NOMBRE).write_bytes(_pdf_minimo(LINEAS))
    (origen / "142" / "2026-10" / "RECHAZADO_20261106143005.pdf").write_bytes(b"x")
    (origen / "142" / "2026-10" / "01_formulario_20261106.png").write_bytes(b"png")
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path / "Zero" / "Declaraciones")
    monkeypatch.setattr(settings, "EVIDENCE_DIR", tmp_path / "Zero" / "Evidencias")
    return origen


def _destino(tmp_path):
    return tmp_path / "Zero" / "Declaraciones" / RUC / "2011 - Declaraci\u00f3n de IVA" / NOMBRE


def test_por_defecto_solo_simula(tmp_path, monkeypatch, capsys):
    origen = _preparar(tmp_path, monkeypatch)
    assert mv.main(["--origen", str(origen)]) == 0
    assert (origen / "142" / "2026-10" / NOMBRE).exists() and not _destino(tmp_path).exists()
    out = capsys.readouterr().out
    assert "SIMULACION" in out and "Se moverian: 1" in out and RUC not in out  # el RUC solo sale enmascarado


def test_aplicar_mueve_el_comprobante_y_no_toca_lo_demas(tmp_path, monkeypatch):
    origen = _preparar(tmp_path, monkeypatch)
    assert mv.main(["--origen", str(origen), "--aplicar"]) == 0
    assert _destino(tmp_path).exists() and not (origen / "142" / "2026-10" / NOMBRE).exists()
    assert (origen / "142" / "2026-10" / "RECHAZADO_20261106143005.pdf").exists()  # los rechazados no se mueven
    assert (origen / "142" / "2026-10" / "01_formulario_20261106.png").exists()  # las capturas, solo con --capturas


def test_es_idempotente_y_no_sobrescribe(tmp_path, monkeypatch, capsys):
    origen = _preparar(tmp_path, monkeypatch)
    mv.main(["--origen", str(origen), "--aplicar"])
    capsys.readouterr()
    assert mv.main(["--origen", str(origen), "--aplicar"]) == 0
    assert "Movidos: 0" in capsys.readouterr().out


def test_no_sobrescribe_un_destino_existente(tmp_path, monkeypatch):
    origen = _preparar(tmp_path, monkeypatch)
    destino = _destino(tmp_path)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"ya habia uno distinto")
    mv.main(["--origen", str(origen), "--aplicar"])
    assert destino.read_bytes() == b"ya habia uno distinto" and (origen / "142" / "2026-10" / NOMBRE).exists()


def test_capturas_se_mueven_a_evidencias_conservando_la_estructura(tmp_path, monkeypatch):
    origen = _preparar(tmp_path, monkeypatch)
    mv.main(["--origen", str(origen), "--aplicar", "--capturas"])
    assert (tmp_path / "Zero" / "Evidencias" / "142" / "2026-10" / "01_formulario_20261106.png").exists()


def test_origen_inexistente(tmp_path, monkeypatch, capsys):
    _preparar(tmp_path, monkeypatch)
    assert mv.main(["--origen", str(tmp_path / "no_existe")]) == 1