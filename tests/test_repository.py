import pytest

from src.database.models import Estado
from src.database.repository import Repositorio


@pytest.fixture
def repo():
    r = Repositorio(":memory:")
    yield r
    r.cerrar()


def test_una_fila_por_fideicomiso_y_periodo(repo):
    repo.marcar("1", "2026-10", Estado.EN_PROCESO, intento=True)
    repo.marcar("1", "2026-10", Estado.SIMULADO)
    assert repo.estado("1", "2026-10") == Estado.SIMULADO
    assert repo.estado("1", "2026-11") is None
    assert repo._db.execute("SELECT COUNT(*) FROM declaraciones").fetchone()[0] == 1


def test_cuenta_intentos(repo):
    for _ in range(3):
        repo.marcar("1", "2026-10", Estado.EN_PROCESO, intento=True)
    assert repo._db.execute("SELECT intentos FROM declaraciones").fetchone()[0] == 3


def test_eventos_son_de_solo_anexar(repo):
    repo.marcar("1", "2026-10", Estado.EN_PROCESO, intento=True)
    repo.marcar("1", "2026-10", Estado.ERROR, "fallo")
    repo.marcar("1", "2026-10", Estado.SIMULADO)
    estados = [f[0] for f in repo._db.execute("SELECT estado FROM eventos ORDER BY id")]
    assert estados == ["en_proceso", "error", "simulado"]


def test_el_detalle_no_guarda_secretos(repo):
    repo.marcar("1", "2026-10", Estado.ERROR, "fallo con password=secreto123 y token=abc")
    detalle = repo._db.execute("SELECT detalle FROM declaraciones").fetchone()[0]
    assert "secreto123" not in detalle and "abc" not in detalle


def test_recupera_las_interrumpidas(repo):
    repo.marcar("1", "2026-10", Estado.EN_PROCESO, intento=True)
    repo.marcar("2", "2026-10", Estado.SIMULADO)
    repo.marcar("3", "2026-09", Estado.EN_PROCESO, intento=True)  # otro periodo: no se toca
    assert repo.recuperar_interrumpidas("2026-10") == 1
    assert repo.estado("1", "2026-10") == Estado.REVISION_MANUAL
    assert repo.estado("2", "2026-10") == Estado.SIMULADO
    assert repo.estado("3", "2026-09") == Estado.EN_PROCESO


def test_ciclo_de_una_ejecucion(repo):
    ejec = repo.iniciar_ejecucion("0.2.0", True, "contador", "2026-10", "usuario")
    repo.cerrar_ejecucion(ejec, "procesados=1")
    fin, resumen = repo._db.execute("SELECT fin, resumen FROM ejecuciones WHERE id=?", (ejec,)).fetchone()
    assert fin and resumen == "procesados=1"
