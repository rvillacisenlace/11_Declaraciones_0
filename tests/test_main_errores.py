import logging

import main
from src.utils.exceptions import ConfigError


def _falla(*_a, **_k):
    raise ConfigError("falta algo en la configuracion")


def test_error_controlado_antes_del_navegador_se_registra(monkeypatch, caplog):
    monkeypatch.setattr(main.settings, "validar", _falla)
    with caplog.at_level(logging.ERROR):
        assert main.main(["--contribuyente", "C001", "--login", "manual"]) == 1
    assert "ConfigError" in caplog.text and "falta algo" in caplog.text


def test_error_al_cargar_credenciales_se_registra(monkeypatch, caplog):
    monkeypatch.setattr(main.settings, "validar", lambda: None)
    monkeypatch.setattr("builtins.input", lambda *_: "SI")
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: "clave")
    monkeypatch.setattr(main, "_cargar_credenciales", _falla)
    with caplog.at_level(logging.ERROR):
        assert main.main(["--contribuyente", "C001", "--login", "manual", "--hasta", "contador"]) == 1
    assert "falta algo" in caplog.text
