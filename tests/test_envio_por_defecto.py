import pytest

import main
from config import settings
from src.sri import retenciones
from tests import test_main_lote as _base
from tests.test_todo_lo_marcado import _filas, _preparar

entorno = _base.entorno  # fixture compartida (settings, credenciales, navegador y capturas simulados)


def _grabar(monkeypatch):
    """Sustituye los dos flujos por grabadores: (impuesto, id, hasta, kwargs)."""
    visto = []

    def flujo(ctx, page, cid, per, hasta, cred, cont, **kw):
        visto.append(("2011", cid, hasta, kw))
        return "comprobante serie 1" if kw.get("enviar") else None

    def recorrer(ctx, page, cid, per, hasta, cred, cont, **kw):
        visto.append(("1031", cid, hasta, kw))
        return "comprobante serie 2" if kw.get("enviar") else None
    monkeypatch.setattr(main, "_flujo", flujo)
    monkeypatch.setattr(retenciones, "recorrer", recorrer)
    return visto


def test_py_main_a_secas_procesa_todo_lo_marcado_y_envia_cuando_dry_run_es_false(entorno, monkeypatch):
    _, tmp = entorno
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr("builtins.input", lambda *_: "SI")
    assert main.main(["--pausa", "0"]) == 0  # sin --lote, sin --hasta, sin --enviar
    assert [(i, c) for i, c, _, _ in visto] == [("2011", "A1"), ("2011", "A2"), ("1031", "B1"), ("1031", "B2")]
    assert all(h == "contador" and kw.get("enviar") is True for _, _, h, kw in visto)
    assert all(estado == "declarado" for _, _, estado in _filas(tmp))


def test_con_dry_run_true_py_main_a_secas_solo_simula(entorno, monkeypatch):
    _, tmp = entorno
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    preguntas = []
    monkeypatch.setattr(settings, "DRY_RUN", True)
    monkeypatch.setattr("builtins.input", lambda p="": preguntas.append(p) or "SI")
    assert main.main(["--pausa", "0"]) == 0
    assert len(visto) == 4 and all("enviar" not in kw for _, _, _, kw in visto)
    assert all(estado == "simulado" for _, _, estado in _filas(tmp))
    assert preguntas[0].startswith("SIMULACION") and "REALES" not in preguntas[0]


def test_simular_no_envia_aunque_dry_run_sea_false(entorno, monkeypatch):
    _, tmp = entorno
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    assert main.main(["--simular", "--pausa", "0"]) == 0
    assert len(visto) == 4 and all("enviar" not in kw for _, _, _, kw in visto)
    assert all(estado == "simulado" for _, _, estado in _filas(tmp))


def test_simular_y_enviar_son_incompatibles():
    with pytest.raises(SystemExit):
        main.main(["--simular", "--enviar"])


def test_un_recorrido_parcial_nunca_envia_aunque_dry_run_sea_false(entorno, monkeypatch):
    _, tmp = entorno
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    assert main.main(["--hasta", "firma", "--pausa", "0"]) == 0
    assert len(visto) == 4 and all("enviar" not in kw and h == "firma" for _, _, h, kw in visto)
    assert all(estado == "parcial" for _, _, estado in _filas(tmp))


@pytest.mark.parametrize("respuesta", ["", "no", "si", "ENVIAR", "enviar"])
def test_cualquier_respuesta_distinta_de_SI_no_envia_nada(entorno, monkeypatch, respuesta):
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    monkeypatch.setattr("builtins.input", lambda *_: respuesta)
    assert main.main(["--pausa", "0"]) == 1
    assert visto == []


def test_incluir_revision_se_rechaza_cuando_se_va_a_enviar_pero_se_acepta_al_simular(entorno, monkeypatch):
    _preparar(monkeypatch)
    _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    with pytest.raises(SystemExit):
        main.main(["--incluir-revision", "--pausa", "0"])  # DRY_RUN=false: iria a enviar
    assert main.main(["--incluir-revision", "--simular", "--pausa", "0"]) == 0
    monkeypatch.setattr(settings, "DRY_RUN", True)
    assert main.main(["--incluir-revision", "--pausa", "0"]) == 0


def test_un_fideicomiso_suelto_nunca_envia_aunque_dry_run_sea_false(entorno, monkeypatch):
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    assert main.main(["--contribuyente", "R1", "--login", "manual", "--credenciales", "consola"]) == 0
    assert len(visto) == 1 and "enviar" not in visto[0][3] and visto[0][2] == "periodo"


def test_el_envio_explicito_sigue_bloqueado_con_dry_run_true(entorno, monkeypatch):
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", True)
    assert main.main(["--enviar", "--pausa", "0"]) == 1
    assert visto == []


def test_un_fideicomiso_suelto_no_envia_ni_siquiera_con_hasta_contador_explicito(entorno, monkeypatch):
    # El caso peligroso: DRY_RUN=false y el recorrido completo, pero para UN fideicomiso. Solo el lote envia.
    _preparar(monkeypatch)
    visto = _grabar(monkeypatch)
    monkeypatch.setattr(settings, "DRY_RUN", False)
    respuestas = iter(["SI", "1710000000001"])  # confirmacion previa y RUC del contador
    monkeypatch.setattr("builtins.input", lambda *_: next(respuestas))
    argv = ["--contribuyente", "R1", "--login", "manual", "--credenciales", "consola", "--hasta", "contador"]
    assert main.main(argv) == 0
    assert len(visto) == 1 and "enviar" not in visto[0][3] and visto[0][2] == "contador"
