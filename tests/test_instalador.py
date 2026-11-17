"""El instalador no se puede compilar en las pruebas (hace falta Inno Setup en Windows): aqui se vigilan las reglas que
si se pueden comprobar leyendo los archivos, para que un cambio descuidado no las rompa sin que nadie lo note."""
import re
from pathlib import Path

import pytest

from config import settings

RAIZ = Path(__file__).resolve().parent.parent
ISS = (RAIZ / "zero_instalador.iss").read_text(encoding="utf-8")
SPEC = (RAIZ / "zero.spec").read_text(encoding="utf-8")
ENV_EJEMPLO = (RAIZ / ".env.example").read_text(encoding="utf-8")


def _define(nombre: str) -> str:
    return re.search(rf'#define {nombre} "([^"]*)"', ISS).group(1)


def test_la_version_del_instalador_es_la_del_programa():
    assert _define("VersionApp") == settings.VERSION


def test_el_appid_es_un_guid_propio():
    guid = re.search(r"AppId=\{\{([0-9A-F-]{36})\}", ISS).group(1)
    assert re.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", guid)
    assert guid not in ("00000000-0000-0000-0000-000000000000",)


def test_instalacion_por_usuario_sin_administrador():
    assert "PrivilegesRequired=lowest" in ISS and "{userpf}" in ISS


def test_el_instalador_y_el_spec_hablan_del_mismo_exe():
    assert _define("EjecutableApp") == f'{re.search(r"NOMBRE = .(\w+).", SPEC).group(1)}.exe'
    assert 'ENTRADA = "zero_app.py"' in SPEC and "console=True" in SPEC


def test_el_secreto_nunca_se_escribe_al_env():
    assert "MICROSOFT_CLIENT_SECRET" not in ISS
    assert "MICROSOFT_SECRET_TARGET={#DestinoSecreto}" in ISS
    assert _define("DestinoSecreto") == re.search(r"MICROSOFT_SECRET_TARGET=(\S+)", ENV_EJEMPLO).group(1)


def test_produccion_siempre_envia_de_verdad():
    assert "Env.Add('DRY_RUN=false')" in ISS


def test_el_env_no_se_pisa_al_reinstalar():
    assert "if FileExists(RutaEnv) then" in ISS


def test_el_instalador_solo_escribe_variables_que_existen():
    escritas = set(re.findall(r"Env\.Add\('([A-Z_]+)=", ISS))
    conocidas = set(re.findall(r"^#?\s*([A-Z_]+)=", ENV_EJEMPLO, re.M))
    assert escritas and escritas <= conocidas, escritas - conocidas


def test_el_instalador_trae_la_simulacion():
    assert 'Parameters: "--simular"' in ISS


def test_script_solo_ascii():
    assert ISS.isascii()
