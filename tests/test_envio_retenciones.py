import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

import main
from config import settings
from src.sri import retenciones, submission
from src.sri import verification as v
from src.utils.exceptions import ComprobanteInvalido, RecargosInesperados
from tests import test_main_lote as _base
from tests.test_submission import _Pagina
from tests.test_verificacion import HOY, LINEAS, PERIODO, RUC, _pdf_minimo

entorno = _base.entorno  # fixture compartida (settings y credenciales simulados)

# Comprobante de retenciones: el nombre del impuesto ocupa DOS lineas, como en el PDF real.
LINEAS_RET = [l for l in LINEAS if not l.startswith("Impuesto")]
_i = next(k for k, l in enumerate(LINEAS_RET) if l.startswith("Período"))
LINEAS_RET[_i + 1:_i + 1] = ["Impuesto: 1031 - DECLARACIÓN DE RETENCIONES EN LA", "FUENTE"]
AHORA = datetime(2026, 11, 6, 14, 30, 5)


# el verificador distingue el impuesto
def test_el_nombre_del_impuesto_en_dos_lineas_se_lee_completo():
    assert v.parsear("\n".join(LINEAS_RET)).impuesto == "1031 - DECLARACION DE RETENCIONES EN LA FUENTE"
    assert v.parsear("\n".join(LINEAS)).impuesto == "2011 DECLARACION DE IVA"


def test_cada_comprobante_solo_vale_para_su_impuesto():
    ret, iva = v.parsear("\n".join(LINEAS_RET)), v.parsear("\n".join(LINEAS))
    v.verificar(ret, RUC, PERIODO, HOY, impuesto="1031")
    v.verificar(iva, RUC, PERIODO, HOY)
    with pytest.raises(ComprobanteInvalido, match="2011"):
        v.verificar(ret, RUC, PERIODO, HOY)  # por defecto se espera IVA
    with pytest.raises(ComprobanteInvalido, match="1031"):
        v.verificar(iva, RUC, PERIODO, HOY, impuesto="1031")


def test_archivar_pide_el_impuesto_correcto(tmp_path):
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(_pdf_minimo(LINEAS_RET))
    with pytest.raises(ComprobanteInvalido):
        v.archivar(pdf, tmp_path / "ev", RUC, PERIODO, ahora=AHORA, hoy=HOY)  # como IVA: se rechaza
    assert pdf.exists() and not (tmp_path / "ev").exists()
    final = v.archivar(pdf, tmp_path / "ev", RUC, PERIODO, ahora=AHORA, hoy=HOY, impuesto="1031")
    assert final.name == f"111111111111_{RUC}_20261106143005.pdf" and final.exists() and not pdf.exists()


# el envio llega hasta la verificacion con el impuesto
def test_el_envio_de_retenciones_se_verifica_como_retenciones(tmp_path):
    p = _Pagina(pdf=_pdf_minimo(LINEAS_RET))
    ruta = submission.enviar_declaracion(p, RUC, PERIODO, tmp_path / "ev", envio_autorizado=True, hoy=HOY, ahora=AHORA,
                                         impuesto="1031")
    assert ruta.exists()


def test_un_comprobante_de_retenciones_no_se_acepta_como_iva_ni_al_reves(tmp_path):
    p = _Pagina(pdf=_pdf_minimo(LINEAS_RET))
    with pytest.raises(ComprobanteInvalido, match="2011"):
        submission.enviar_declaracion(p, RUC, PERIODO, tmp_path / "ev", envio_autorizado=True, hoy=HOY, ahora=AHORA)
    assert [f.name[:10] for f in (tmp_path / "ev").iterdir()] == ["RECHAZADO_"]
    p = _Pagina()  # comprobante de IVA
    with pytest.raises(ComprobanteInvalido, match="1031"):
        submission.enviar_declaracion(p, RUC, PERIODO, tmp_path / "ev2", envio_autorizado=True, hoy=HOY, ahora=AHORA,
                                      impuesto="1031")


# retenciones.recorrer solo envia si se le ordena
class _Ruta:
    name = "999_1790000000001_20261106143005.pdf"


def _preparar(monkeypatch, llamadas, orden=None, falla_recargos=None):
    def paso(nombre, falla=None):
        def f(*a, **k):
            if orden is not None:
                orden.append(nombre)
            if falla:
                raise falla
        return f

    def envio(*a, **k):
        if orden is not None:
            orden.append("enviar")
        llamadas.append((a, k))
        return _Ruta()
    monkeypatch.setattr(retenciones.authentication, "iniciar_sesion", lambda *a, **k: None)
    monkeypatch.setattr(retenciones, "abrir_formulario", lambda p: None)
    for nombre in ("seleccionar_obligacion", "seleccionar_periodo", "rechazar_si_ya_declarado"):
        monkeypatch.setattr(retenciones.declaration, nombre, lambda *a, **k: None)
    for nombre in ("siguiente", "responder_no", "siguiente_perfilador"):
        monkeypatch.setattr(retenciones, nombre, paso(nombre))
    monkeypatch.setattr(retenciones, "verificar_sin_recargos", paso("recargos", falla_recargos))
    monkeypatch.setattr(retenciones.signature, "llenar_contador", paso("contador"))
    monkeypatch.setattr(retenciones, "capturar", lambda *a: None)
    monkeypatch.setattr(retenciones.submission, "enviar_declaracion", envio)


def test_sin_enviar_nunca_se_llama_al_envio(monkeypatch):
    llamadas = []
    _preparar(monkeypatch, llamadas)
    assert retenciones.recorrer(None, object(), "A1", PERIODO, "contador", object(), object()) is None
    assert llamadas == []


def test_aunque_se_ordene_enviar_no_se_envia_si_el_recorrido_se_corta_antes(monkeypatch):
    llamadas = []
    _preparar(monkeypatch, llamadas)
    for hasta in ("periodo", "siguiente", "valores", "firma"):
        retenciones.recorrer(None, object(), "A1", PERIODO, hasta, object(), object(), enviar=True, ruc=RUC)
    assert llamadas == []


def test_con_enviar_se_llama_una_vez_autorizado_con_el_impuesto_y_la_carpeta_de_retenciones(monkeypatch):
    llamadas = []
    _preparar(monkeypatch, llamadas)
    r = retenciones.recorrer(None, object(), "A1", PERIODO, "contador", object(), object(), enviar=True, ruc=RUC,
                             responsable="Resp1")
    assert r == "comprobante serie 999" and len(llamadas) == 1
    args, kw = llamadas[0]
    assert kw["envio_autorizado"] is True and kw["impuesto"] == "1031" and args[1] == RUC and callable(kw["evidencia"])
    assert Path(args[3]).name == "1031 - Declaraci\u00f3n de retenciones en la fuente"
    assert Path(args[3]).parent == settings.DECLARACIONES_DIR / "Resp1" / RUC / "10-2026"


def test_el_envio_ocurre_despues_de_todos_los_pasos_y_en_este_orden(monkeypatch):
    orden = []
    _preparar(monkeypatch, [], orden)
    retenciones.recorrer(None, object(), "A1", PERIODO, "contador", object(), object(), enviar=True, ruc=RUC)
    assert orden == ["siguiente", "responder_no", "siguiente_perfilador", "contador", "recargos", "enviar"]


def test_un_recargo_impide_el_envio(monkeypatch):
    llamadas, orden = [], []
    _preparar(monkeypatch, llamadas, orden, falla_recargos=RecargosInesperados("multa 1.00"))
    with pytest.raises(RecargosInesperados):
        retenciones.recorrer(None, object(), "A1", PERIODO, "contador", object(), object(), enviar=True, ruc=RUC)
    assert llamadas == [] and "enviar" not in orden


# main: lote de retenciones con --enviar
def _teclado(monkeypatch, respuestas):
    it = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _abrir(monkeypatch):
    @contextmanager
    def abrir():
        yield type("Ctx", (), {"pages": [], "new_page": lambda self: object()})()
    monkeypatch.setattr(main, "open_context", abrir)


def _recorrer_falso(llamadas):
    def falso(ctx, page, cid, per, hasta, cred, cont, **kw):
        llamadas.append((cid, kw))
        return "comprobante serie 999" if kw.get("enviar") else None
    return falso


def test_con_dry_run_el_envio_de_retenciones_esta_bloqueado(entorno, monkeypatch):
    llamadas, _ = entorno
    monkeypatch.setattr(settings, "DRY_RUN", True)
    _abrir(monkeypatch)
    monkeypatch.setattr(retenciones, "recorrer", _recorrer_falso(llamadas["flujo"]))
    _teclado(monkeypatch, ["SI", "ENVIAR"])
    assert main.main(["--lote", "--impuesto", "1031", "--enviar", "--max", "1", "--hasta", "contador"]) == 1
    assert llamadas["flujo"] == [] and llamadas["creds"] == []


@pytest.mark.parametrize("respuesta", ["", "enviar", "si", "no", "ENVIAR"])
def test_sin_la_confirmacion_exacta_no_se_envian_retenciones(entorno, monkeypatch, respuesta):
    llamadas, _ = entorno
    monkeypatch.setattr(settings, "DRY_RUN", False)
    _abrir(monkeypatch)
    monkeypatch.setattr(retenciones, "recorrer", _recorrer_falso(llamadas["flujo"]))
    _teclado(monkeypatch, [respuesta])
    assert main.main(["--lote", "--impuesto", "1031", "--enviar", "--max", "1", "--hasta", "contador"]) == 1
    assert llamadas["flujo"] == []


def test_envio_autorizado_de_retenciones_pasa_enviar_y_ruc_y_deja_declarado_en_1031(entorno, monkeypatch):
    llamadas, tmp = entorno
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    _abrir(monkeypatch)
    monkeypatch.setattr(retenciones, "recorrer", _recorrer_falso(llamadas["flujo"]))
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: llamadas["flujo"].append("IVA"))
    _teclado(monkeypatch, ["SI", "ENVIAR"])
    assert main.main(["--lote", "--impuesto", "1031", "--enviar", "--max", "1", "--hasta", "contador", "--pausa", "0"]) == 0
    assert llamadas["flujo"] == [("A1", {"enviar": True, "ruc": "1790000000001", "responsable": "Resp1"})]
    con = sqlite3.connect(str(tmp / "execution_history.db"))
    assert con.execute("SELECT fideicomiso_id, impuesto, estado FROM declaraciones").fetchall() == [("A1", "1031", "declarado")]
    con.close()