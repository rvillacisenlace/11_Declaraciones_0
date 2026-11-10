from contextlib import contextmanager

import pytest

import main
from src.sri import retenciones
from src.utils.exceptions import RecargosInesperados
from tests import test_main_lote as _base

entorno = _base.entorno  # fixture compartida (settings y credenciales simulados)


class _Campo:
    def __init__(self, valor):
        self.valor = valor

    def count(self):
        return 0 if self.valor is None else 1

    @property
    def first(self):
        return self

    def input_value(self, timeout=None):
        return self.valor


class _Pagina:
    def __init__(self, interes=None, multa=None):
        self.campos = {retenciones.CAMPOS_RECARGO["interes"]: _Campo(interes),
                       retenciones.CAMPOS_RECARGO["multa"]: _Campo(multa)}

    def locator(self, sel):
        return self.campos[sel]


@pytest.mark.parametrize("interes,multa", [("0.00", "0.00"), ("0,00", "0,00"), ("", ""), (None, None), ("$ 0.00", "0")])
def test_sin_recargos_pasa(interes, multa):
    retenciones.verificar_sin_recargos(_Pagina(interes, multa))


@pytest.mark.parametrize("interes,multa,nombre", [("1.50", "0.00", "interes"), ("0.00", "0,05", "multa"), ("10", None, "interes")])
def test_cualquier_recargo_detiene_antes_de_enviar(interes, multa, nombre):
    with pytest.raises(RecargosInesperados, match=nombre):
        retenciones.verificar_sin_recargos(_Pagina(interes, multa))

def test_el_envio_solo_existe_en_el_lote_tambien_para_retenciones():
    with pytest.raises(SystemExit):
        main.main(["--contribuyente", "5", "--impuesto", "1031", "--enviar", "--max", "1", "--hasta", "contador"])

def test_con_impuesto_1031_se_usa_el_recorrido_de_retenciones_y_no_el_del_iva(entorno, monkeypatch):
    llamadas = []

    @contextmanager
    def abrir():
        yield type("Ctx", (), {"pages": [], "new_page": lambda self: object()})()
    monkeypatch.setattr(main, "open_context", abrir)
    monkeypatch.setattr("builtins.input", lambda *_: "SI")
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    monkeypatch.setattr(retenciones, "recorrer", lambda *a: llamadas.append(("ret", a[2], a[4])))
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: llamadas.append(("iva",)))
    argv = ["--contribuyente", "R1", "--impuesto", "1031", "--login", "manual", "--credenciales", "consola"]
    assert main.main(argv + ["--hasta", "periodo"]) == 0
    assert llamadas == [("ret", "R1", "periodo")]
    llamadas.clear()
    assert main.main(["--contribuyente", "R1", "--login", "manual", "--credenciales", "consola", "--hasta", "periodo"]) == 0
    assert llamadas == [("iva",)]


def test_siguiente_perfilador_distingue_la_pregunta_por_su_texto():
    # La pantalla siguiente (resumen) tambien trae filas con la clase respuestas-perfilamiento (la del contador):
    # si la fila se buscara solo por esa clase, se creeria que el portal no avanzo.
    import inspect
    assert "has_text=sel.PREGUNTA_VALORES" in inspect.getsource(retenciones.siguiente_perfilador)