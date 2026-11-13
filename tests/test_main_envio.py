import pytest

import main
from config import settings
from src.sri import submission
from tests import test_main_lote as _base
from src.utils.exceptions import RecargosInesperados

entorno = _base.entorno  # fixture compartida
_estado = _base._estado


def _teclado(monkeypatch, respuestas):
    it = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _flujo_falso(llamadas):
    def falso(ctx, page, cid, per, hasta, cred, cont, **kw):
        llamadas.append((cid, kw))
        return "comprobante serie 999" if kw.get("enviar") else None
    return falso


@pytest.mark.parametrize("argv", [
    ["--enviar"],
    ["--enviar", "--lote", "--max", "1"],
    ["--enviar", "--lote", "--max", "1", "--hasta", "firma"],
    ["--enviar", "--contribuyente", "5", "--max", "1", "--hasta", "contador"],
])
def test_enviar_exige_lote_y_hasta_contador(argv):
    with pytest.raises(SystemExit):
        main.main(argv)


def test_con_dry_run_el_envio_esta_bloqueado_y_no_se_hace_nada(entorno, monkeypatch):
    llamadas, _ = entorno
    monkeypatch.setattr(settings, "DRY_RUN", True)
    monkeypatch.setattr(main, "_flujo", _flujo_falso(llamadas["flujo"]))
    _teclado(monkeypatch, ["SI", "ENVIAR"])
    assert main.main(["--lote", "--enviar", "--max", "1", "--hasta", "contador"]) == 1
    assert llamadas["flujo"] == [] and llamadas["creds"] == []


@pytest.mark.parametrize("segunda", ["", "enviar", "SI", "no"])
def test_sin_la_segunda_confirmacion_exacta_no_se_envia(entorno, monkeypatch, segunda):
    llamadas, _ = entorno
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(main, "_flujo", _flujo_falso(llamadas["flujo"]))
    _teclado(monkeypatch, ["SI", segunda])
    assert main.main(["--lote", "--enviar", "--max", "1", "--hasta", "contador"]) == 1
    assert llamadas["flujo"] == []


def test_envio_autorizado_pasa_enviar_y_ruc_y_deja_declarado(entorno, monkeypatch):
    llamadas, tmp = entorno
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr(main, "_flujo", _flujo_falso(llamadas["flujo"]))
    _teclado(monkeypatch, ["SI", "ENVIAR"])
    assert main.main(["--lote", "--enviar", "--max", "1", "--hasta", "contador", "--pausa", "0"]) == 0
    assert llamadas["flujo"] == [("A1", {"enviar": True, "ruc": "1790000000001", "responsable": "Resp1"})]
    assert _estado(tmp, "A1") == "declarado"


def test_sin_enviar_nunca_se_pasa_la_orden_de_enviar(entorno, monkeypatch):
    llamadas, _ = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr(main, "_flujo", _flujo_falso(llamadas["flujo"]))
    assert main.main(["--lote", "--hasta", "contador", "--max", "2", "--pausa", "0"]) == 0
    assert llamadas["flujo"] and all("enviar" not in kw for _, kw in llamadas["flujo"])  # ruc y responsable si; la orden de enviar, nunca


def _preparar_flujo(monkeypatch, llamadas):
    monkeypatch.setattr(main.authentication, "iniciar_sesion", lambda *a, **k: None)
    monkeypatch.setattr(main.navigation, "abrir_formulario_iva", lambda p: None)
    for nombre in ("seleccionar_obligacion", "seleccionar_periodo", "siguiente", "rechazar_si_ya_declarado", "responder_valores_no", "siguiente_perfilador"):
        monkeypatch.setattr(main.declaration, nombre, lambda *a, **k: None)
    monkeypatch.setattr(main.signature, "llenar_contador", lambda *a, **k: None)
    monkeypatch.setattr(main.retenciones, "verificar_sin_recargos", lambda *a, **k: None)
    monkeypatch.setattr(main, "capturar", lambda *a: None)
    monkeypatch.setattr(submission, "enviar_declaracion", lambda *a, **k: llamadas.append((a, k)) or _Ruta())


class _Ruta:
    name = "999_1790000000001_20261106143005.pdf"


def test_flujo_sin_enviar_nunca_llama_al_envio(monkeypatch):
    llamadas = []
    _preparar_flujo(monkeypatch, llamadas)
    assert main._flujo(None, object(), "A1", (2026, 10), "contador", object(), object()) is None
    assert llamadas == []


def test_flujo_con_enviar_llama_una_vez_autorizado_y_devuelve_la_serie(monkeypatch):
    llamadas = []
    _preparar_flujo(monkeypatch, llamadas)
    r = main._flujo(None, object(), "A1", (2026, 10), "contador", object(), object(), enviar=True, ruc="1790000000001")
    assert r == "comprobante serie 999" and len(llamadas) == 1
    assert llamadas[0][1]["envio_autorizado"] is True and llamadas[0][0][1] == "1790000000001"


def test_el_iva_revisa_los_recargos_despues_del_contador_y_antes_de_enviar(monkeypatch):
    orden = []
    _preparar_flujo(monkeypatch, [])
    monkeypatch.setattr(main.signature, "llenar_contador", lambda *a, **k: orden.append("contador"))
    monkeypatch.setattr(main.retenciones, "verificar_sin_recargos", lambda *a, **k: orden.append("recargos"))
    monkeypatch.setattr(submission, "enviar_declaracion", lambda *a, **k: orden.append("enviar") or _Ruta())
    main._flujo(None, object(), "A1", (2026, 10), "contador", object(), object(), enviar=True, ruc="1790000000001")
    assert orden == ["contador", "recargos", "enviar"]


def test_un_recargo_en_el_iva_impide_el_envio(monkeypatch):
    llamadas = []
    _preparar_flujo(monkeypatch, llamadas)

    def falla(*a, **k):
        raise RecargosInesperados("multa 1.00")
    monkeypatch.setattr(main.retenciones, "verificar_sin_recargos", falla)
    with pytest.raises(RecargosInesperados):
        main._flujo(None, object(), "A1", (2026, 10), "contador", object(), object(), enviar=True, ruc="1790000000001")
    assert llamadas == []