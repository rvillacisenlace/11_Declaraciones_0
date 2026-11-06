"""Red de seguridad: pulsar 'Aceptar' ENVIA la declaracion y no se deshace. Solo puede ocurrir en UN lugar:
la funcion enviar_declaracion de submission.py, y una sola vez. Nada mas en src/ puede actuar sobre ese boton,
ni sobre 'Nueva declaracion'. Si se cambia el diseño del envio, estas pruebas se actualizan a proposito."""
import ast
from pathlib import Path

import pytest

from src.security.credential_repository import Credencial
from src.sri import signature
from src.utils.exceptions import ConfigError

SRC = Path(__file__).resolve().parents[1] / "src"
ACCIONES = {"click", "dblclick", "tap", "press", "press_sequentially", "dispatch_event", "check", "set_checked"}
ID_ACEPTAR = "divBotonContinuarConfirmacion"
ID_NUEVA_DECLARACION = "btnSinValorPagarNuevaDeclaracion"
ARCHIVO_DEL_ENVIO, FUNCION_DEL_ENVIO = "submission.py", "enviar_declaracion"


def _menciona_aceptar(nodo) -> bool:
    for n in ast.walk(nodo):
        if isinstance(n, ast.Name) and n.id == "BOTON_ACEPTAR":
            return True
        if isinstance(n, ast.Attribute) and n.attr == "BOTON_ACEPTAR":
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and ID_ACEPTAR in n.value:
            return True
    return False


def _acciones_sobre_aceptar(archivo: Path) -> list[tuple[int, str]]:
    """(linea, funcion) de cada accion sobre el boton Aceptar, directa o por una variable que lo guarda."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    alias = {t.id for n in ast.walk(arbol) if isinstance(n, ast.Assign) and _menciona_aceptar(n.value)
             for t in n.targets if isinstance(t, ast.Name)}
    funcion_de = {}
    for f in ast.walk(arbol):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for hijo in ast.walk(f):
                funcion_de[id(hijo)] = f.name
    acciones = []
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ACCIONES:
            usa_alias = any(isinstance(x, ast.Name) and x.id in alias for x in ast.walk(n))
            if _menciona_aceptar(n) or usa_alias:
                acciones.append((n.lineno, funcion_de.get(id(n), "<modulo>")))
    return acciones


@pytest.mark.parametrize("archivo", sorted(SRC.rglob("*.py")), ids=lambda p: str(p.relative_to(SRC)))
def test_solo_la_funcion_del_envio_actua_sobre_aceptar(archivo):
    acciones = _acciones_sobre_aceptar(archivo)
    if archivo.name == ARCHIVO_DEL_ENVIO:
        assert len(acciones) == 1 and acciones[0][1] == FUNCION_DEL_ENVIO, \
            f"se esperaba UN solo clic en {FUNCION_DEL_ENVIO}; hay: {acciones}"
    else:
        assert acciones == [], f"{archivo.name} actua sobre el boton Aceptar: eso envia la declaracion"


def test_el_id_del_boton_aceptar_solo_vive_en_signature():
    otros = [p.name for p in SRC.rglob("*.py") if p.name != "signature.py" and ID_ACEPTAR in p.read_text(encoding="utf-8")]
    assert otros == []


def test_nunca_se_menciona_nueva_declaracion():
    assert [p.name for p in SRC.rglob("*.py") if ID_NUEVA_DECLARACION in p.read_text(encoding="utf-8")] == []


def test_llenar_contador_nunca_pulsa_aceptar_ni_aunque_se_le_pida():
    import inspect
    assert "enviar" not in inspect.signature(signature.llenar_contador).parameters


def test_una_clave_con_salto_de_linea_se_rechaza_antes_de_tocar_la_pagina():
    # Un Enter dentro del campo de la clave enviaria el formulario: page=None prueba que ni se llega a la pantalla.
    c = Credencial("contador", "contador", "1710000000001", "ab\ncd")
    with pytest.raises(ConfigError, match="caracteres de control"):
        signature.llenar_contador(None, c)