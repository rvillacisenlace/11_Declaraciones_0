from pathlib import Path

from openpyxl import Workbook

from config import settings
from diagnostics import mover_comprobantes as mv
from src.utils.rutas import nombre_carpeta
from tests.test_envio_retenciones import LINEAS_RET
from tests.test_verificacion import LINEAS, RUC, _pdf_minimo

NOMBRE = f"111111111111_{RUC}_20261106143005.pdf"
IVA = "2011 - Declaraci\u00f3n de IVA"
RET = "1031 - Declaraci\u00f3n de retenciones en la fuente"
RESP = "Justin P\u00e9rez"


def _control(tmp_path, filas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fideicomisos"
    ws.append(["ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"])
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def _entorno(tmp_path, monkeypatch, filas=None):
    filas = [["142", "x", RUC, "NO", "NO", RESP]] if filas is None else filas
    monkeypatch.setattr(settings, "DECLARACIONES_DIR", tmp_path / "Zero" / "Declaraciones")
    monkeypatch.setattr(settings, "EVIDENCE_DIR", tmp_path / "Zero" / "Evidencias")
    ruta = _control(tmp_path, filas)
    monkeypatch.setattr(mv, "ruta_control", lambda: ruta)
    antiguo = tmp_path / "antiguo"
    antiguo.mkdir()
    return antiguo


def _decl(tmp_path, *partes):
    return tmp_path / "Zero" / "Declaraciones" / Path(*partes)


def _viejo(antiguo, lineas=LINEAS, nombre=NOMBRE):
    carpeta = antiguo / "142" / "2026-10"
    carpeta.mkdir(parents=True)
    (carpeta / nombre).write_bytes(_pdf_minimo(lineas))
    return carpeta / nombre


def test_por_defecto_solo_simula(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch)
    pdf = _viejo(antiguo)
    assert mv.main(["--origen", str(antiguo)]) == 0
    assert pdf.exists() and not (tmp_path / "Zero" / "Declaraciones").exists()
    out = capsys.readouterr().out
    assert "SIMULACION" in out and "Se moverian: 1" in out and RUC not in out  # el RUC solo sale enmascarado


def test_aplicar_mueve_el_comprobante_a_su_responsable_y_no_toca_lo_demas(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    pdf = _viejo(antiguo)
    (pdf.parent / "RECHAZADO_20261106143005.pdf").write_bytes(b"x")
    assert mv.main(["--origen", str(antiguo), "--aplicar"]) == 0
    assert _decl(tmp_path, RESP, RUC, "10-2026", IVA, NOMBRE).exists() and not pdf.exists()
    assert (pdf.parent / "RECHAZADO_20261106143005.pdf").exists()  # los rechazados no se mueven


def test_las_retenciones_van_a_su_propia_carpeta(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    _viejo(antiguo, LINEAS_RET)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert _decl(tmp_path, RESP, RUC, "10-2026", RET, NOMBRE).exists()


def test_reorganiza_lo_que_ya_estaba_en_el_esquema_anterior_sin_responsable(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    anterior = _decl(tmp_path, RUC, IVA)
    anterior.mkdir(parents=True)
    (anterior / NOMBRE).write_bytes(_pdf_minimo(LINEAS))
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert _decl(tmp_path, RESP, RUC, "10-2026", IVA, NOMBRE).exists()
    assert not _decl(tmp_path, RUC).exists()  # las carpetas vacias del esquema anterior se quitan


def test_se_limpian_las_carpetas_antiguas_que_quedan_vacias_pero_no_la_raiz(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    pdf = _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert not pdf.parent.exists() and not pdf.parent.parent.exists() and antiguo.exists()


def test_es_idempotente(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch)
    _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    capsys.readouterr()
    assert mv.main(["--origen", str(antiguo), "--aplicar"]) == 0
    assert "Movidos: 0" in capsys.readouterr().out


def test_no_sobrescribe_un_destino_existente(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch)
    pdf = _viejo(antiguo)
    destino = _decl(tmp_path, RESP, RUC, "10-2026", IVA, NOMBRE)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"ya habia uno distinto")
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert destino.read_bytes() == b"ya habia uno distinto" and pdf.exists()
    assert "ya existian: 1" in capsys.readouterr().out


def test_un_ruc_que_no_esta_en_el_control_se_deja_donde_esta(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch, filas=[["1", "x", "1790000000099", "NO", "NO", RESP]])
    pdf = _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert pdf.exists() and not (tmp_path / "Zero" / "Declaraciones").exists()
    assert "sin responsable: 1" in capsys.readouterr().out


def test_responsable_vacio_va_a_sin_responsable(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch, filas=[["142", "x", RUC, "NO", "NO", None]])
    _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert _decl(tmp_path, "SIN RESPONSABLE", RUC, "10-2026", IVA, NOMBRE).exists()


def test_un_responsable_con_caracteres_invalidos_se_normaliza(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch, filas=[["142", "x", RUC, "NO", "NO", "Ana/Luz:*"]])
    _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert _decl(tmp_path, nombre_carpeta("Ana/Luz:*"), RUC, "10-2026", IVA, NOMBRE).exists()


def test_un_ruc_con_dos_responsables_distintos_no_se_mueve(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch, filas=[["1", "x", RUC, "NO", "NO", "Ana"], ["2", "y", RUC, "NO", "NO", "Luis"]])
    pdf = _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    out = capsys.readouterr().out
    assert pdf.exists() and "AVISO" in out and "sin responsable: 1" in out


def test_reorganiza_el_esquema_actual_que_aun_no_tiene_carpeta_de_periodo(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    actual = _decl(tmp_path, RESP, RUC, IVA)  # Responsable/RUC/impuesto, sin periodo
    actual.mkdir(parents=True)
    (actual / NOMBRE).write_bytes(_pdf_minimo(LINEAS))
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert _decl(tmp_path, RESP, RUC, "10-2026", IVA, NOMBRE).exists()
    assert not actual.exists()  # la carpeta de impuesto sin periodo quedo vacia y se quita


def test_cada_comprobante_va_a_la_carpeta_de_su_propio_periodo(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    otro = f"222222222222_{RUC}_20270206143005.pdf"
    carpeta = antiguo / "142" / "2027-01"
    carpeta.mkdir(parents=True)
    (carpeta / otro).write_bytes(_pdf_minimo([l.replace("OCTUBRE 2026", "ENERO 2027") for l in LINEAS]))
    _viejo(antiguo)
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert _decl(tmp_path, RESP, RUC, "10-2026", IVA, NOMBRE).exists()
    assert _decl(tmp_path, RESP, RUC, "01-2027", IVA, otro).exists()


def test_un_periodo_que_no_se_reconoce_se_informa_y_no_se_mueve(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch)
    pdf = _viejo(antiguo, [l.replace("OCTUBRE 2026", "OCTUBREX 2026") for l in LINEAS])
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert pdf.exists() and "ilegibles: 1" in capsys.readouterr().out


# ------------------------------------------------------------------ capturas
def _evid(tmp_path, *partes):
    return tmp_path / "Zero" / "Evidencias" / Path(*partes)


def _por_id(raiz, id_="142", nombre="ret_04_pregunta_no_20261110_122653.png"):
    """Esquema mas antiguo: <ID>/<AAAA-MM>/<archivo>."""
    carpeta = raiz / id_ / "2026-10"
    carpeta.mkdir(parents=True)
    (carpeta / nombre).write_bytes(b"png")
    return carpeta / nombre


def _plana(tmp_path, nombre, resp=RESP):
    """Esquema anterior: <Responsable>/<RUC>/<archivo>."""
    carpeta = _evid(tmp_path, resp, RUC)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_bytes(b"png")
    return carpeta / nombre


def test_las_capturas_solo_se_mueven_con_la_opcion(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    png = _por_id(antiguo)
    plana = _plana(tmp_path, "2026-10_2011_01_periodo_20261112_153114.png")
    mv.main(["--origen", str(antiguo), "--aplicar"])
    assert png.exists() and plana.exists()


def test_una_captura_del_esquema_antiguo_va_al_periodo_y_al_impuesto_que_le_corresponden(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    ret = _por_id(antiguo)  # ret_... -> retenciones
    iva = _por_id(tmp_path / "Zero" / "Evidencias", nombre="07_declarada_20261109_085627.png")  # sin ret_ -> IVA
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert _evid(tmp_path, RESP, RUC, "10-2026", RET, "2026-10_1031_04_pregunta_no_20261110_122653.png").exists()
    assert _evid(tmp_path, RESP, RUC, "10-2026", IVA, "2026-10_2011_07_declarada_20261109_085627.png").exists()
    assert not ret.exists() and not iva.exists()
    assert not _evid(tmp_path, "142").exists()  # la carpeta antigua por ID quedo vacia y se quita


def test_una_captura_plana_con_codigo_de_impuesto_se_acomoda_en_su_carpeta_sin_cambiar_de_nombre(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    nombre = "2026-10_2011_01_periodo_20261112_153114.png"
    png = _plana(tmp_path, nombre)
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert _evid(tmp_path, RESP, RUC, "10-2026", IVA, nombre).exists() and not png.exists()


def test_una_captura_plana_de_la_primera_migracion_sin_codigo_se_normaliza(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    _plana(tmp_path, "2026-10_ret_04_pregunta_no_20261110_122653.png")
    _plana(tmp_path, "2026-10_07_declarada_20261109_085627.png")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert _evid(tmp_path, RESP, RUC, "10-2026", RET, "2026-10_1031_04_pregunta_no_20261110_122653.png").exists()
    assert _evid(tmp_path, RESP, RUC, "10-2026", IVA, "2026-10_2011_07_declarada_20261109_085627.png").exists()


def test_cada_captura_va_a_la_carpeta_de_su_propio_periodo(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    _plana(tmp_path, "2027-01_1031_02_preguntas_20270206_101010.png")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert _evid(tmp_path, RESP, RUC, "01-2027", RET, "2027-01_1031_02_preguntas_20270206_101010.png").exists()


def test_una_captura_de_un_id_que_no_esta_en_el_control_se_deja(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch)
    png = _por_id(antiguo, id_="R1")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert png.exists() and "no estan en el Control" in capsys.readouterr().out


def test_las_capturas_que_ya_estan_en_el_esquema_actual_no_se_tocan(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    ya = _evid(tmp_path, RESP, RUC, "10-2026", IVA, "2026-10_2011_01_periodo_20261112_153114.png")
    ya.parent.mkdir(parents=True)
    ya.write_bytes(b"png")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert ya.exists()


def test_el_movimiento_de_capturas_es_idempotente(tmp_path, monkeypatch, capsys):
    antiguo = _entorno(tmp_path, monkeypatch)
    _plana(tmp_path, "2026-10_2011_01_periodo_20261112_153114.png")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    capsys.readouterr()
    assert mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"]) == 0
    assert "capturas: 0" in capsys.readouterr().out


def test_no_sobrescribe_una_captura_existente(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    nombre = "2026-10_2011_01_periodo_20261112_153114.png"
    origen = _plana(tmp_path, nombre)
    destino = _evid(tmp_path, RESP, RUC, "10-2026", IVA, nombre)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"otra")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert destino.read_bytes() == b"otra" and origen.exists()


def test_un_archivo_con_nombre_desconocido_se_deja_donde_esta(tmp_path, monkeypatch):
    antiguo = _entorno(tmp_path, monkeypatch)
    raro = _plana(tmp_path, "foto.png")
    mv.main(["--origen", str(antiguo), "--aplicar", "--capturas"])
    assert raro.exists()


def test_origen_inexistente_o_control_ilegible(tmp_path, monkeypatch):
    _entorno(tmp_path, monkeypatch)
    assert mv.main(["--origen", str(tmp_path / "no_existe")]) == 1
    monkeypatch.setattr(mv, "ruta_control", lambda: None)
    assert mv.main(["--origen", str(tmp_path / "antiguo")]) == 1