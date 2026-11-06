from contextlib import contextmanager

import pytest

import main
from config import settings
from src.database.repository import Repositorio
from src.security.credential_repository import Credencial
from src.services.fideicomiso_service import Fideicomiso, ResultadoControl
from src.utils.exceptions import PortalChanged


class _Ctx:
    pages = []

    def new_page(self):
        return object()


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    llamadas = {"flujo": [], "capturas": [], "creds": []}
    fids = [Fideicomiso(2, "A1", "N", "1790000000001", "Resp1"), Fideicomiso(3, "A2", "N", "1790000000002", "Resp2"),
            Fideicomiso(4, "A3", "N", "1790000000003", "Resp1")]
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "validar", lambda: None)
    monkeypatch.setattr(main, "leer_control", lambda _r: ResultadoControl(10, 7, fids, []))
    monkeypatch.setattr(main, "ruta_control", lambda: None)
    monkeypatch.setattr(main, "cruzar_credenciales", lambda pend, _c: (pend, []))
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: "maestra")
    monkeypatch.setattr("builtins.input", lambda *_: "SI")
    monkeypatch.setattr(main.credential_repository, "cargar_contribuyente",
                        lambda i, r, _c: llamadas["creds"].append(i) or Credencial(i, "contribuyente", r, "x"))
    monkeypatch.setattr(main.credential_repository, "cargar_contador",
                        lambda _c: Credencial("contador", "contador", "1710000000001", "y"))
    monkeypatch.setattr(main, "capturar", lambda *a: llamadas["capturas"].append(a[-1]))

    @contextmanager
    def fake_open():
        yield _Ctx()
    monkeypatch.setattr(main, "open_context", fake_open)
    monkeypatch.setattr(main, "_flujo", lambda ctx, page, cid, per, hasta, cred, cont: llamadas["flujo"].append(cid))
    return llamadas, tmp_path


def _estado(tmp_path, fid):
    with Repositorio(tmp_path / "execution_history.db") as r:
        return r.estado(fid, "2026-10").value


def test_lote_procesa_todos_y_guarda_el_estado(entorno, monkeypatch):
    llamadas, tmp = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    assert main.main(["--lote", "--hasta", "contador", "--pausa", "0"]) == 0
    assert llamadas["flujo"] == ["A1", "A2", "A3"] and llamadas["creds"] == ["A1", "A2", "A3"]
    assert all(_estado(tmp, i) == "simulado" for i in ("A1", "A2", "A3"))


def test_lote_con_hasta_parcial_queda_como_parcial(entorno, monkeypatch):
    llamadas, tmp = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    assert main.main(["--lote", "--hasta", "periodo", "--pausa", "0", "--max", "1"]) == 0
    assert llamadas["flujo"] == ["A1"] and _estado(tmp, "A1") == "parcial"


def test_sin_confirmacion_no_procesa_nada(entorno, monkeypatch):
    llamadas, _ = entorno
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    assert main.main(["--lote", "--pausa", "0"]) == 1
    assert llamadas["flujo"] == [] and llamadas["creds"] == []


def test_portal_cambiado_detiene_el_lote_y_devuelve_codigo_3(entorno, monkeypatch):
    llamadas, tmp = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))

    def falla(ctx, page, cid, per, hasta, cred, cont):
        llamadas["flujo"].append(cid)
        if cid == "A2":
            raise PortalChanged("selector")
    monkeypatch.setattr(main, "_flujo", falla)
    assert main.main(["--lote", "--pausa", "0"]) == 3
    assert llamadas["flujo"] == ["A1", "A2"] and "error" in llamadas["capturas"]
    assert _estado(tmp, "A2") == "revision_manual"


@pytest.mark.parametrize("argv", [
    [], ["--lote", "--contribuyente", "5"], ["--lote", "--login", "manual"],
    ["--lote", "--credenciales", "consola"], ["--lote", "--max", "0"]])
def test_combinaciones_de_argumentos_invalidas(argv):
    with pytest.raises(SystemExit):
        main.main(argv)
