import subprocess
import sys

import pytest
import requests

from src.microsoft import authentication as auth
from src.utils.exceptions import ConfigError, GraphError


class AppFalsa:
    def __init__(self, resultado=None, error=None):
        self.resultado, self.error, self.pedidos = resultado, error, 0

    def acquire_token_for_client(self, scopes):
        self.pedidos += 1
        assert scopes == ["https://graph.microsoft.com/.default"]
        if self.error:
            raise self.error
        return self.resultado


def _auth(app, creadas=None):
    def crear(tenant, client, secreto):
        if creadas is not None:
            creadas.append((tenant, client, secreto))
        return app
    return auth.AutenticacionGraph("t", "c", "s3cr3to-largo", crear_app=crear)


def test_devuelve_el_token():
    assert _auth(AppFalsa({"access_token": "abc"})).token() == "abc"


def test_error_de_microsoft_no_deja_ver_el_secreto():
    app = AppFalsa({"error": "invalid_client", "error_description": "el secreto s3cr3to-largo no es valido"})
    with pytest.raises(GraphError) as e:
        _auth(app).token()
    assert "invalid_client" in str(e.value) and "s3cr3to-largo" not in str(e.value)


def test_excepcion_inesperada_se_envuelve_sin_detalle():
    with pytest.raises(GraphError) as e:
        _auth(AppFalsa(error=ValueError("s3cr3to-largo"))).token()
    assert "s3cr3to-largo" not in str(e.value) and "ValueError" in str(e.value)


def test_error_de_red_se_deja_pasar_para_reintentar():
    with pytest.raises(requests.exceptions.ConnectionError):
        _auth(AppFalsa(error=requests.exceptions.ConnectionError("x"))).token()


def test_renovar_crea_una_aplicacion_nueva():
    creadas = []
    a = _auth(AppFalsa({"access_token": "abc"}), creadas)
    a.renovar()
    assert len(creadas) == 2 and creadas[0] == creadas[1] == ("t", "c", "s3cr3to-largo")


def test_fallo_al_crear_msal_se_envuelve_sin_secreto(monkeypatch):
    import msal

    def rota(**kw):
        raise ValueError("no se pudo con s3cr3to-largo")
    monkeypatch.setattr(auth, "usar_almacen_del_sistema", lambda: None)
    monkeypatch.setattr(msal, "ConfidentialClientApplication", rota)
    with pytest.raises(GraphError) as e:
        auth.AutenticacionGraph("t", "c", "s3cr3to-largo")
    assert "s3cr3to-largo" not in str(e.value) and "MICROSOFT_TENANT_ID" in str(e.value)


def test_truststore_se_inyecta_antes_de_crear_msal(monkeypatch):
    import msal
    import truststore
    orden = []
    monkeypatch.setitem(auth._TLS, "listo", False)
    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: orden.append("truststore"))
    monkeypatch.setattr(msal, "ConfidentialClientApplication", lambda **kw: orden.append("msal") or object())
    auth.AutenticacionGraph("t", "c", "s")
    assert orden == ["truststore", "msal"]


def test_msal_recibe_timeout(monkeypatch):
    import msal
    recibido = {}
    monkeypatch.setattr(auth, "usar_almacen_del_sistema", lambda: None)
    monkeypatch.setattr(msal, "ConfidentialClientApplication", lambda **kw: recibido.update(kw) or object())
    auth.AutenticacionGraph("tenant-x", "client-y", "s")
    assert recibido["timeout"] == 30 and recibido["authority"].endswith("/tenant-x") and recibido["client_id"] == "client-y"


# ---- lectura de la credencial guardada con cmdkey (UTF-16) ----

def test_blob_utf16_de_cmdkey():
    assert auth._decodificar_blob("secreto~Ab.1".encode("utf-16-le")) == "secreto~Ab.1"


def test_blob_utf8():
    assert auth._decodificar_blob(b"secreto") == "secreto"


@pytest.mark.parametrize("blob", [b"", b"\xff\xfe\xfd", b"\x01\x02\x03", "\x00".encode("utf-16-le")])
def test_blob_ilegible_o_vacio(blob):
    assert auth._decodificar_blob(blob) is None


def test_fuera_de_windows_no_hay_almacen(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert auth.leer_credencial_windows("Zero.MicrosoftSecret") is None


# ---- de donde sale el secreto ----

@pytest.fixture
def avisos(monkeypatch):
    registro = []
    monkeypatch.setattr(auth.log, "warning", lambda msg, *a: registro.append(msg % a if a else msg))
    monkeypatch.setitem(auth._AVISO, "texto_plano", False)
    return registro


def test_el_almacen_de_windows_tiene_prioridad(monkeypatch, avisos):
    monkeypatch.setenv("MICROSOFT_SECRET_TARGET", "Zero.X")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "del-env")
    monkeypatch.setattr(auth, "leer_credencial_windows", lambda destino: "del-almacen" if destino == "Zero.X" else None)
    assert auth.obtener_secreto() == "del-almacen"
    assert auth.origen_del_secreto() == "Administrador de credenciales" and not avisos


def test_sin_almacen_usa_el_env_y_avisa_una_sola_vez(monkeypatch, avisos):
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "del-env")
    assert auth.obtener_secreto() == "del-env" and auth.obtener_secreto() == "del-env"
    assert len(avisos) == 1 and "texto plano" in avisos[0] and "del-env" not in avisos[0]
    assert auth.origen_del_secreto().startswith(".env")


def test_credencial_inexistente_cae_al_env_y_lo_dice(monkeypatch, avisos):
    monkeypatch.setenv("MICROSOFT_SECRET_TARGET", "Zero.NoExiste")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "del-env")
    monkeypatch.setattr(auth, "leer_credencial_windows", lambda destino: None)
    assert auth.obtener_secreto() == "del-env"
    assert any("Zero.NoExiste" in a for a in avisos)


def test_sin_secreto_en_ninguna_parte(monkeypatch, avisos):
    assert auth.origen_del_secreto() is None
    with pytest.raises(ConfigError, match="MICROSOFT_SECRET_TARGET"):
        auth.obtener_secreto()


# ---- solo en Windows: el Administrador de credenciales real ----

pytestmark_windows = pytest.mark.skipif(sys.platform != "win32", reason="solo en Windows")


@pytestmark_windows
def test_windows_credencial_inexistente():
    assert auth.leer_credencial_windows("Zero.Prueba.NoExiste.NoUsar") is None


@pytestmark_windows
def test_windows_cmdkey_ida_y_vuelta():
    destino = "Zero.Prueba.Temporal.NoUsar"
    try:
        subprocess.run(["cmdkey", f"/generic:{destino}", "/user:zero", "/pass:valor-de-prueba~1"], check=True, capture_output=True)
        assert auth.leer_credencial_windows(destino) == "valor-de-prueba~1"
    finally:
        subprocess.run(["cmdkey", f"/delete:{destino}"], capture_output=True)
