import pytest
import requests

from src.microsoft import graph_client
from src.microsoft.graph_client import BASE, ClienteGraph
from src.utils.exceptions import GraphError
from tests.graph_falsos import AutenticacionFalsa, RespuestaFalsa, SesionFalsa


@pytest.fixture(autouse=True)
def _sin_truststore(monkeypatch):
    monkeypatch.setattr(graph_client, "usar_almacen_del_sistema", lambda: None)


def _cliente(*respuestas, reintentos=4):
    esperas = []
    auth = AutenticacionFalsa()
    sesion = SesionFalsa(*respuestas)
    return ClienteGraph(auth, sesion=sesion, dormir=esperas.append, reintentos=reintentos), sesion, auth, esperas


def test_lleva_token_timeout_y_prefijo():
    c, sesion, _, _ = _cliente(RespuestaFalsa(200, {"ok": 1}))
    assert c.get_json("/drives/d/items/i", contexto="x") == {"ok": 1}
    llamada = sesion.llamadas[0]
    assert llamada["url"] == BASE + "/drives/d/items/i"
    assert llamada["headers"]["Authorization"] == "Bearer token-1"
    assert llamada["timeout"] == (10, 60)


def test_url_absoluta_no_se_prefija():
    c, sesion, _, _ = _cliente(RespuestaFalsa(200, {}))
    c.get_json("https://graph.microsoft.com/v1.0/otra", contexto="x")
    assert sesion.llamadas[0]["url"] == "https://graph.microsoft.com/v1.0/otra"


def test_patch_envia_el_cuerpo():
    c, sesion, _, _ = _cliente(RespuestaFalsa(200, {}))
    c.patch_json("/r", {"values": [["DECLARADO"]]}, contexto="x")
    assert sesion.llamadas[0]["metodo"] == "PATCH" and sesion.llamadas[0]["json"] == {"values": [["DECLARADO"]]}


def test_descargar_devuelve_bytes_y_acepta_cualquier_tipo():
    c, sesion, _, _ = _cliente(RespuestaFalsa(200, contenido=b"\x00\x01datos"))
    assert c.descargar("/r/content", contexto="x") == b"\x00\x01datos"
    assert sesion.llamadas[0]["headers"]["Accept"] == "*/*"


def test_429_respeta_retry_after():
    c, sesion, _, esperas = _cliente(RespuestaFalsa(429, cabeceras={"Retry-After": "3"}), RespuestaFalsa(200, {"ok": 1}))
    assert c.get_json("/r", contexto="x") == {"ok": 1}
    assert esperas == [3.0] and len(sesion.llamadas) == 2


def test_503_espera_creciente_sin_retry_after():
    c, _, _, esperas = _cliente(RespuestaFalsa(503), RespuestaFalsa(502), RespuestaFalsa(200, {}))
    c.get_json("/r", contexto="x")
    assert esperas == [1.0, 2.0]


def test_retry_after_enorme_se_acota():
    c, _, _, esperas = _cliente(RespuestaFalsa(429, cabeceras={"Retry-After": "99999"}), RespuestaFalsa(200, {}))
    c.get_json("/r", contexto="x")
    assert esperas == [60.0]


def test_se_rinde_tras_los_reintentos():
    c, sesion, _, _ = _cliente(*[RespuestaFalsa(503)] * 3, reintentos=2)
    with pytest.raises(GraphError) as e:
        c.get_json("/r", contexto="leer el Control")
    assert e.value.status == 503 and len(sesion.llamadas) == 3 and "leer el Control" in str(e.value)


def test_error_de_red_se_reintenta():
    c, sesion, _, esperas = _cliente(requests.exceptions.ConnectionError("x"), RespuestaFalsa(200, {"ok": 1}))
    assert c.get_json("/r", contexto="x") == {"ok": 1}
    assert len(sesion.llamadas) == 2 and len(esperas) == 1


def test_error_de_red_persistente_no_filtra_la_url():
    c, _, _, _ = _cliente(*[requests.exceptions.Timeout("https://graph.microsoft.com/secreto?sig=abc")] * 3, reintentos=2)
    with pytest.raises(GraphError) as e:
        c.get_json("/r", contexto="leer el Control")
    assert "sig=abc" not in str(e.value) and "Timeout" in str(e.value)


def test_401_renueva_el_token_una_vez():
    c, sesion, auth, _ = _cliente(RespuestaFalsa(401), RespuestaFalsa(200, {"ok": 1}))
    assert c.get_json("/r", contexto="x") == {"ok": 1}
    assert auth.renovaciones == 1
    assert sesion.llamadas[0]["headers"]["Authorization"] != sesion.llamadas[1]["headers"]["Authorization"]


def test_dos_401_seguidos_fallan_sin_bucle():
    c, sesion, auth, _ = _cliente(RespuestaFalsa(401), RespuestaFalsa(401))
    with pytest.raises(GraphError) as e:
        c.get_json("/r", contexto="x")
    assert e.value.status == 401 and auth.renovaciones == 1 and len(sesion.llamadas) == 2


def test_404_no_se_reintenta_y_solo_informa_el_codigo():
    cuerpo = {"error": {"code": "itemNotFound", "message": "detalle interno con datos privados"}}
    c, sesion, _, esperas = _cliente(RespuestaFalsa(404, cuerpo))
    with pytest.raises(GraphError) as e:
        c.get_json("/r", contexto="encontrar el archivo")
    assert e.value.status == 404 and "itemNotFound" in str(e.value)
    assert "privados" not in str(e.value) and not esperas and len(sesion.llamadas) == 1


def test_error_sin_cuerpo_json():
    c, _, _, _ = _cliente(RespuestaFalsa(403))
    with pytest.raises(GraphError, match="sin codigo"):
        c.get_json("/r", contexto="x")
