import io

import pytest
from msoffcrypto.format.ooxml import OOXMLFile
from openpyxl import Workbook

from config import settings
from diagnostics import diag_graph
from src.microsoft import authentication, fuentes
from src.microsoft.excel_repository import ControlGraph
from src.utils.exceptions import GraphError
from tests.graph_falsos import ClienteControlFalso

ENC = ["ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"]
FILAS = [ENC, ["A1", "Fideicomiso Secreto", "1790000000001", "SI", "NO", "Ana"],
         ["A2", "Otro", "1790000000002", "NO", "SI", "Luis"]]


class ClienteDiag:
    def __init__(self, respuestas=None, falla=None):
        self.respuestas, self.rutas, self.falla = respuestas or {}, [], falla

    def get_json(self, ruta, *, contexto):
        self.rutas.append(ruta)
        if self.falla:
            raise self.falla
        for fin, valor in self.respuestas.items():
            if ruta.endswith(fin):
                return valor
        raise AssertionError(ruta)

    def probar_token(self):
        if self.falla:
            raise self.falla


class ArchivoDiag:
    def __init__(self, datos):
        self.datos = datos

    def leer_bytes(self):
        return self.datos


def _libro(cifrar):
    wb = Workbook()
    plano = io.BytesIO()
    wb.save(plano)
    if not cifrar:
        return plano.getvalue()
    plano.seek(0)
    salida = io.BytesIO()
    OOXMLFile(plano).encrypt("maestra", salida)
    return salida.getvalue()


def _entorno(monkeypatch, control=True, credenciales=True):
    if control:
        monkeypatch.setenv("GRAPH_CONTROL_DRIVE_ID", "d")
        monkeypatch.setenv("GRAPH_CONTROL_ITEM_ID", "i")
    if credenciales:
        monkeypatch.setenv("GRAPH_CREDENCIALES_DRIVE_ID", "d")
        monkeypatch.setenv("GRAPH_CREDENCIALES_ITEM_ID", "j")
    monkeypatch.setattr(authentication, "origen_del_secreto", lambda: ".env (texto plano)")
    monkeypatch.setattr(fuentes, "cliente_graph", lambda: ClienteDiag())
    monkeypatch.setattr(fuentes, "control_graph", lambda: ControlGraph(ClienteControlFalso(FILAS), "d", "i") if control else None)


def test_sin_graph_no_hay_nada_que_comprobar(capsys):
    assert diag_graph.verificar() == 0
    assert "Graph no esta activado" in capsys.readouterr().out


def test_todo_correcto_y_sin_datos_sensibles(monkeypatch, capsys):
    _entorno(monkeypatch)
    monkeypatch.setattr(fuentes, "credenciales_graph", lambda: ArchivoDiag(_libro(True)))
    assert diag_graph.verificar() == 0
    salida = capsys.readouterr().out
    assert "todo correcto" in salida and "1 pendientes" in salida
    for prohibido in ("Fideicomiso Secreto", "1790000000001", "Ana", "maestra"):
        assert prohibido not in salida


def test_credenciales_sin_cifrar_falla(monkeypatch, capsys):
    _entorno(monkeypatch, control=False)
    monkeypatch.setattr(fuentes, "credenciales_graph", lambda: ArchivoDiag(_libro(False)))
    assert diag_graph.verificar() == 1
    assert "NO esta cifrado" in capsys.readouterr().out


def test_credenciales_que_no_son_un_libro(monkeypatch, capsys):
    _entorno(monkeypatch, control=False)
    monkeypatch.setattr(fuentes, "credenciales_graph", lambda: ArchivoDiag(b"basura"))
    assert diag_graph.verificar() == 1
    assert "no es un libro de Excel" in capsys.readouterr().out


def test_sin_secreto_se_detiene(monkeypatch, capsys):
    _entorno(monkeypatch)
    monkeypatch.setattr(authentication, "origen_del_secreto", lambda: None)
    assert diag_graph.verificar() == 1
    assert "NO ENCONTRADO" in capsys.readouterr().out


def test_falla_el_token_y_no_sigue(monkeypatch, capsys):
    _entorno(monkeypatch)
    monkeypatch.setattr(fuentes, "cliente_graph", lambda: ClienteDiag(falla=GraphError("sin token")))
    assert diag_graph.verificar() == 1
    salida = capsys.readouterr().out
    assert "sin token" in salida and "Control leido" not in salida


def test_configuracion_a_medias_se_informa(monkeypatch, capsys):
    monkeypatch.setenv("GRAPH_CONTROL_DRIVE_ID", "solo-drive")
    assert diag_graph.verificar() == 0
    salida = capsys.readouterr().out
    assert "FALLA" in salida and "GRAPH_CONTROL_ITEM_ID" in salida


# ---- --buscar ----

def test_buscar_usa_los_endpoints_y_codifica_la_ruta():
    cl = ClienteDiag({"/drive": {"id": "b!drive"}, "Control%20SRI.xlsx": {"id": "01ITEM"}})
    assert diag_graph.buscar(cl, "u@enlace.ec", "/COMPARTIDO/Declaraciones/Control SRI.xlsx") == ("b!drive", "01ITEM")
    assert cl.rutas == ["/users/u@enlace.ec/drive", "/users/u@enlace.ec/drive/root:/COMPARTIDO/Declaraciones/Control%20SRI.xlsx"]


def test_main_buscar_muestra_los_ids_sin_escribir(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(settings, "HOME", tmp_path)
    monkeypatch.setattr(fuentes, "cliente_graph", lambda: ClienteDiag({"/drive": {"id": "D"}, "a.xlsx": {"id": "I"}}))
    assert diag_graph.main(["--buscar", "u@x.ec", "a.xlsx", "--como", "control"]) == 0
    assert "GRAPH_CONTROL_DRIVE_ID=D" in capsys.readouterr().out and not (tmp_path / ".env").exists()


def test_main_buscar_escribe_en_el_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "HOME", tmp_path)
    (tmp_path / ".env").write_text("DRY_RUN=false\n", encoding="utf-8")
    monkeypatch.setattr(fuentes, "cliente_graph", lambda: ClienteDiag({"/drive": {"id": "D"}, "a.xlsx": {"id": "I"}}))
    assert diag_graph.main(["--buscar", "u@x.ec", "a.xlsx", "--como", "credenciales", "--escribir"]) == 0
    texto = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DRY_RUN=false" in texto and "GRAPH_CREDENCIALES_DRIVE_ID='D'" in texto.replace('"', "'") and "ITEM_ID" in texto


def test_main_buscar_con_error(monkeypatch, capsys):
    monkeypatch.setattr(fuentes, "cliente_graph", lambda: ClienteDiag(falla=GraphError("Graph no pudo: HTTP 404")))
    assert diag_graph.main(["--buscar", "u@x.ec", "a.xlsx", "--como", "control"]) == 1
    assert "HTTP 404" in capsys.readouterr().out


def test_escribir_exige_buscar_y_como():
    with pytest.raises(SystemExit):
        diag_graph.main(["--escribir"])
    with pytest.raises(SystemExit):
        diag_graph.main(["--buscar", "u@x.ec", "a.xlsx", "--escribir"])
