from config import settings
from src.services.fideicomiso_service import Fideicomiso, cruzar_credenciales
from tests.test_credentials import CLAVE_LIBRO, _xlsx_cifrado


def _f(fila, id_, ruc):
    return Fideicomiso(fila, id_, "N", ruc, "R")


def test_cruce_separa_listos_y_excluidos(tmp_path, monkeypatch):
    filas = [[1, "1790000000001", "a", None], [2, "1790000000002", None, None],
             [3, "1790000000003", "x", None], [4, "1790000000003", "y", None]]
    monkeypatch.setattr(settings, "CREDENCIALES_XLSX", _xlsx_cifrado(tmp_path, filas))
    pend = [_f(2, "A", "1790000000001"), _f(3, "B", "1790000000002"), _f(4, "C", "1790000000003"),
            _f(5, "D", "1790000000999")]
    listos, excl = cruzar_credenciales(pend, CLAVE_LIBRO)
    assert [p.id for p in listos] == ["A"]
    assert {e.id: e.motivo.split(" (")[0] for e in excl} == {
        "B": "credencial sin clave", "C": "credencial ambigua", "D": "sin credencial en Accesos"}
