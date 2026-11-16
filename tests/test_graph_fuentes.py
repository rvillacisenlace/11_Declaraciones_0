import pytest

from src.microsoft import authentication, fuentes, graph_client
from src.microsoft.excel_repository import ArchivoGraph, ControlGraph
from src.services.fideicomiso_service import ruta_control
from src.utils.exceptions import ConfigError


class AutFalsa:
    def __init__(self, tenant, client, secreto):
        self.datos = (tenant, client, secreto)


class ClienteFalso:
    creados = 0

    def __init__(self, autenticacion):
        type(self).creados += 1
        self.autenticacion = autenticacion


@pytest.fixture(autouse=True)
def _dobles(monkeypatch):
    monkeypatch.setattr(authentication, "AutenticacionGraph", AutFalsa)
    monkeypatch.setattr(graph_client, "ClienteGraph", ClienteFalso)
    ClienteFalso.creados = 0


def _microsoft(monkeypatch):
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "tenant")
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "client")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "secreto")


def _control(monkeypatch):
    monkeypatch.setenv("GRAPH_CONTROL_DRIVE_ID", "d1")
    monkeypatch.setenv("GRAPH_CONTROL_ITEM_ID", "i1")


def _credenciales(monkeypatch):
    monkeypatch.setenv("GRAPH_CREDENCIALES_DRIVE_ID", "d1")
    monkeypatch.setenv("GRAPH_CREDENCIALES_ITEM_ID", "i2")


def test_sin_configuracion_todo_es_local(monkeypatch):
    monkeypatch.setenv("CONTROL_XLSX", "C:/local/Control.xlsx")
    assert fuentes.control_graph() is None and fuentes.credenciales_graph() is None
    assert str(ruta_control()).replace("\\", "/") == "C:/local/Control.xlsx"


def test_tenant_y_client_solos_no_activan_graph(monkeypatch):
    _microsoft(monkeypatch)
    assert fuentes.control_graph() is None and fuentes.credenciales_graph() is None
    assert ClienteFalso.creados == 0


@pytest.mark.parametrize("variable", ["GRAPH_CONTROL_DRIVE_ID", "GRAPH_CONTROL_ITEM_ID"])
def test_configuracion_a_medias_es_error_y_no_vuelve_a_local(monkeypatch, variable):
    _microsoft(monkeypatch)
    monkeypatch.setenv("CONTROL_XLSX", "C:/local/Control.xlsx")
    monkeypatch.setenv(variable, "x")
    with pytest.raises(ConfigError, match="deben ir las dos"):
        fuentes.control_graph()
    with pytest.raises(ConfigError):
        ruta_control()


def test_credenciales_a_medias(monkeypatch):
    monkeypatch.setenv("GRAPH_CREDENCIALES_ITEM_ID", "x")
    with pytest.raises(ConfigError, match="GRAPH_CREDENCIALES_DRIVE_ID"):
        fuentes.credenciales_graph()


def test_graph_activo_sin_tenant_ni_client(monkeypatch):
    _control(monkeypatch)
    with pytest.raises(ConfigError, match="MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID"):
        fuentes.control_graph()


def test_graph_activo_sin_secreto(monkeypatch):
    _control(monkeypatch)
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "tenant")
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "client")
    with pytest.raises(ConfigError, match="secreto de Microsoft"):
        fuentes.control_graph()


def test_control_completo(monkeypatch):
    _microsoft(monkeypatch)
    _control(monkeypatch)
    c = fuentes.control_graph()
    assert isinstance(c, ControlGraph) and fuentes.control_graph() is c  # el mismo objeto: respalda una sola vez
    assert c._item == "/drives/d1/items/i1"
    assert ruta_control() is c


def test_control_y_credenciales_son_independientes(monkeypatch):
    _microsoft(monkeypatch)
    _control(monkeypatch)
    assert fuentes.credenciales_graph() is None
    assert isinstance(fuentes.control_graph(), ControlGraph)
    _credenciales(monkeypatch)
    cred = fuentes.credenciales_graph()
    assert isinstance(cred, ArchivoGraph) and cred._item == "/drives/d1/items/i2"
    assert ClienteFalso.creados == 1  # ambos comparten un solo cliente


def test_el_cliente_recibe_los_datos_del_env(monkeypatch):
    _microsoft(monkeypatch)
    _control(monkeypatch)
    assert fuentes.control_graph() and fuentes.cliente_graph().autenticacion.datos == ("tenant", "client", "secreto")


def test_reiniciar_olvida_lo_guardado(monkeypatch):
    _microsoft(monkeypatch)
    _control(monkeypatch)
    primero = fuentes.control_graph()
    fuentes.reiniciar()
    assert fuentes.control_graph() is not primero


def test_cambiar_de_archivo_da_otro_objeto(monkeypatch):
    _microsoft(monkeypatch)
    _control(monkeypatch)
    primero = fuentes.control_graph()
    monkeypatch.setenv("GRAPH_CONTROL_ITEM_ID", "otro")
    segundo = fuentes.control_graph()
    assert segundo is not primero and segundo._item == "/drives/d1/items/otro"
