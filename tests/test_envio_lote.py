from dataclasses import dataclass

import pytest

from src.core.process_queue import procesar_lote
from src.database.models import Estado
from src.database.repository import Repositorio
from src.utils.exceptions import ComprobanteInvalido, EnvioIncierto

P, TXT = (2026, 10), "2026-10"


@dataclass
class F:
    id: str


@pytest.fixture
def repo():
    r = Repositorio(":memory:")
    yield r
    r.cerrar()


@pytest.mark.parametrize("excepcion", [EnvioIncierto("x"), ComprobanteInvalido("x")])
def test_un_envio_incierto_detiene_el_lote_y_nunca_se_reintenta(repo, excepcion):
    vistos = []

    def ejecutar(f):
        vistos.append(f.id)
        if f.id == "1":
            raise excepcion
    res = procesar_lote([F("1"), F("2")], P, repo, ejecutar, 1, estado_ok=Estado.DECLARADO)
    assert vistos == ["1"] and res.detenido and repo.estado("1", TXT) == Estado.REVISION_MANUAL
    vistos.clear()
    procesar_lote([F("1"), F("2")], P, repo, ejecutar, 2, estado_ok=Estado.DECLARADO)
    assert "1" not in vistos  # quedo en revision manual: no se vuelve a intentar sola


def test_el_exito_guarda_el_detalle_y_deja_el_estado_final(repo):
    procesar_lote([F("1")], P, repo, lambda f: "comprobante serie 123", 1, estado_ok=Estado.DECLARADO)
    assert repo.estado("1", TXT) == Estado.DECLARADO
    assert repo._db.execute("SELECT detalle FROM declaraciones").fetchone()[0] == "comprobante serie 123"
    vistos = []
    procesar_lote([F("1")], P, repo, lambda f: vistos.append(f.id), 2, estado_ok=Estado.DECLARADO)
    assert vistos == []  # un declarado nunca se repite