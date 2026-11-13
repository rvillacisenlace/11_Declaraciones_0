import sqlite3
from pathlib import Path

import pytest

import main
from config import settings
from src.services.fideicomiso_service import Fideicomiso, ResultadoControl
from src.sri import retenciones
from src.utils.exceptions import PortalChanged
from tests import test_main_lote as _base

entorno = _base.entorno  # fixture compartida (settings, credenciales, navegador y capturas simulados)

IVA = [Fideicomiso(2, "A1", "N", "1790000000001", "R1"), Fideicomiso(3, "A2", "N", "1790000000002", "R2")]
RET = [Fideicomiso(4, "B1", "N", "1790000000003", "R1"), Fideicomiso(5, "B2", "N", "1790000000004", "R2")]


def _preparar(monkeypatch, iva=IVA, ret=RET):
    """Control con marcas distintas por impuesto. Devuelve (marcas_leidas, llamadas_a_iva, llamadas_a_retenciones)."""
    marcas, iva_llamadas, ret_llamadas = [], [], []

    def leer(_r, m="declara_0"):
        marcas.append(m)
        return ResultadoControl(10, 7, iva if m == "declara_0" else ret, [])

    def flujo(ctx, page, cid, per, hasta, cred, cont, **kw):
        iva_llamadas.append((cid, kw))
        return "comprobante serie 1" if kw.get("enviar") else None

    def recorrer(ctx, page, cid, per, hasta, cred, cont, **kw):
        ret_llamadas.append((cid, kw))
        return "comprobante serie 2" if kw.get("enviar") else None
    monkeypatch.setattr(main, "leer_control", leer)
    monkeypatch.setattr(main, "_flujo", flujo)
    monkeypatch.setattr(retenciones, "recorrer", recorrer)
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    return marcas, iva_llamadas, ret_llamadas


def _filas(tmp):
    con = sqlite3.connect(str(tmp / "execution_history.db"))
    try:
        return con.execute("SELECT fideicomiso_id, impuesto, estado FROM declaraciones ORDER BY impuesto, fideicomiso_id").fetchall()
    finally:
        con.close()


def test_por_defecto_un_lote_procesa_iva_y_retenciones_en_una_sola_ejecucion(entorno, monkeypatch):
    _, tmp = entorno
    marcas, iva, ret = _preparar(monkeypatch)
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0"]) == 0
    assert marcas == ["declara_0", "retencion_0"]
    assert [c for c, _ in iva] == ["A1", "A2"] and [c for c, _ in ret] == ["B1", "B2"]
    assert _filas(tmp) == [("B1", "1031", "simulado"), ("B2", "1031", "simulado"),
                           ("A1", "2011", "simulado"), ("A2", "2011", "simulado")]


@pytest.mark.parametrize("impuesto,lee,iva_esperado,ret_esperado", [
    ("2011", ["declara_0"], ["A1", "A2"], []),
    ("1031", ["retencion_0"], [], ["B1", "B2"]),
])
def test_un_impuesto_explicito_procesa_solo_ese(entorno, monkeypatch, impuesto, lee, iva_esperado, ret_esperado):
    marcas, iva, ret = _preparar(monkeypatch)
    assert main.main(["--lote", "--impuesto", impuesto, "--hasta", "contador", "--pausa", "0"]) == 0
    assert marcas == lee and [c for c, _ in iva] == iva_esperado and [c for c, _ in ret] == ret_esperado


def test_impuesto_todos_solo_funciona_con_lote():
    with pytest.raises(SystemExit):
        main.main(["--contribuyente", "5", "--impuesto", "todos"])


def test_el_envio_real_no_exige_max_y_envia_todo_lo_marcado_de_los_dos_impuestos(entorno, monkeypatch):
    _, tmp = entorno
    _, iva, ret = _preparar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(main, "ruta_control", lambda: Path("control.xlsx"))
    anotadas = []
    monkeypatch.setattr(main, "marcar_declarado", lambda ruta, fila, id_, marca, resp: anotadas.append((fila, id_, marca)) or True)
    respuestas = iter(["SI", "ENVIAR"])
    monkeypatch.setattr("builtins.input", lambda *_: next(respuestas))
    assert main.main(["--lote", "--hasta", "contador", "--enviar", "--pausa", "0"]) == 0  # sin --max
    assert all(kw.get("enviar") is True for _, kw in iva + ret) and len(iva) == 2 and len(ret) == 2
    assert _filas(tmp) == [("B1", "1031", "declarado"), ("B2", "1031", "declarado"),
                           ("A1", "2011", "declarado"), ("A2", "2011", "declarado")]
    assert sorted(anotadas) == [(2, "A1", "declara_0"), (3, "A2", "declara_0"), (4, "B1", "retencion_0"), (5, "B2", "retencion_0")]


def test_se_pide_una_sola_vez_la_clave_y_cada_confirmacion_con_el_conteo_de_los_dos_impuestos(entorno, monkeypatch):
    _preparar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    claves, preguntas = [], []
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: claves.append(1) or "maestra")
    respuestas = iter(["SI", "ENVIAR"])
    monkeypatch.setattr("builtins.input", lambda p="": preguntas.append(p) or next(respuestas))
    assert main.main(["--lote", "--hasta", "contador", "--enviar", "--pausa", "0"]) == 0
    assert len(claves) == 1 and len(preguntas) == 2
    assert "4 declaraciones" in preguntas[0] and "IVA: 2" in preguntas[0] and "retenciones: 2" in preguntas[0]
    assert "ENVIARAN hasta 4" in preguntas[1] and "IVA: 2" in preguntas[1] and "retenciones: 2" in preguntas[1]


def test_sin_la_confirmacion_escrita_no_se_envia_nada_de_ninguno_de_los_dos(entorno, monkeypatch):
    _, iva, ret = _preparar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    respuestas = iter(["SI", "enviar"])
    monkeypatch.setattr("builtins.input", lambda *_: next(respuestas))
    assert main.main(["--lote", "--hasta", "contador", "--enviar", "--pausa", "0"]) == 1
    assert iva == [] and ret == []


def test_con_dry_run_el_envio_sigue_bloqueado_aunque_ya_no_se_pida_max(entorno, monkeypatch):
    _, iva, ret = _preparar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", True)
    assert main.main(["--lote", "--hasta", "contador", "--enviar", "--pausa", "0"]) == 1
    assert iva == [] and ret == []


def test_max_limita_el_total_de_la_ejecucion_entre_los_dos_impuestos(entorno, monkeypatch):
    _, iva, ret = _preparar(monkeypatch)
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0", "--max", "3"]) == 0
    assert [c for c, _ in iva] == ["A1", "A2"] and [c for c, _ in ret] == ["B1"]


def test_un_problema_general_en_iva_no_deja_correr_retenciones(entorno, monkeypatch):
    _, tmp = entorno
    _, iva, ret = _preparar(monkeypatch)

    def falla(ctx, page, cid, per, hasta, cred, cont, **kw):
        raise PortalChanged("cambio el portal")
    monkeypatch.setattr(main, "_flujo", falla)
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0"]) == 3
    assert ret == [] and [f[1] for f in _filas(tmp)] == ["2011"]


def test_si_solo_hay_marcados_en_un_impuesto_se_procesa_ese_y_el_conteo_lo_muestra(entorno, monkeypatch):
    _, iva, ret = _preparar(monkeypatch, iva=IVA, ret=[])
    preguntas = []
    monkeypatch.setattr("builtins.input", lambda p="": preguntas.append(p) or "SI")
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0"]) == 0
    assert [c for c, _ in iva] == ["A1", "A2"] and ret == []
    assert "IVA: 2" in preguntas[0] and "retenciones: 0" in preguntas[0]


def test_sin_nada_marcado_no_pide_confirmaciones(entorno, monkeypatch):
    _, iva, ret = _preparar(monkeypatch, iva=[], ret=[])

    def no_debe_preguntar(*_):
        raise AssertionError("no debia preguntar")
    monkeypatch.setattr("builtins.input", no_debe_preguntar)
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0"]) == 0
    assert iva == [] and ret == []


def test_el_resumen_final_separa_los_impuestos(entorno, monkeypatch, capsys):
    _preparar(monkeypatch)
    main.main(["--lote", "--hasta", "contador", "--pausa", "0"])
    salida = capsys.readouterr().out
    assert "IVA: procesados=2" in salida and "retenciones: procesados=2" in salida


def test_incluir_revision_no_se_combina_con_enviar():
    # Los de revision_manual pudieron haberse declarado ya: reintentarlos con --enviar arriesga una declaracion duplicada.
    with pytest.raises(SystemExit):
        main.main(["--lote", "--hasta", "contador", "--enviar", "--incluir-revision"])
