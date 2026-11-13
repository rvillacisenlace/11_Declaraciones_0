import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from openpyxl import Workbook

import main
from src.core.process_queue import procesar_lote
from src.database import repository
from src.database.models import Estado
from src.database.repository import Repositorio
from src.services.fideicomiso_service import Fideicomiso, ResultadoControl, leer_control
from src.sri import retenciones
from src.utils.exceptions import ConfigError
from tests import test_main_lote as _base

entorno = _base.entorno  # fixture compartida (settings y credenciales simulados)
P, TXT = (2026, 10), "2026-10"


@dataclass
class F:
    id: str


# ------------------------------------------------------------------ la base distingue el impuesto
def test_el_mismo_fideicomiso_y_periodo_se_registran_por_impuesto():
    with Repositorio(":memory:") as r:
        r.marcar("1", TXT, Estado.DECLARADO)
        assert r.estado("1", TXT) == Estado.DECLARADO and r.estado("1", TXT, "1031") is None
        r.marcar("1", TXT, Estado.SIMULADO, impuesto="1031")
        assert r.estado("1", TXT) == Estado.DECLARADO and r.estado("1", TXT, "1031") == Estado.SIMULADO
        assert r._db.execute("SELECT COUNT(*) FROM declaraciones").fetchone()[0] == 2


def test_las_interrumpidas_se_recuperan_en_todos_los_impuestos():
    with Repositorio(":memory:") as r:
        r.marcar("1", TXT, Estado.EN_PROCESO, intento=True)
        r.marcar("1", TXT, Estado.EN_PROCESO, intento=True, impuesto="1031")
        assert r.recuperar_interrumpidas(TXT) == 2
        assert r.estado("1", TXT) == Estado.REVISION_MANUAL and r.estado("1", TXT, "1031") == Estado.REVISION_MANUAL


# ------------------------------------------------------------------ migracion de una base antigua
def _base_antigua(ruta):
    """Esquema EXACTO de la version 1 (sin la columna impuesto)."""
    con = sqlite3.connect(str(ruta))
    con.executescript("""
    CREATE TABLE ejecuciones (id INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT NOT NULL, fin TEXT, version TEXT,
        dry_run INTEGER, hasta TEXT, periodo TEXT, usuario TEXT, resumen TEXT);
    CREATE TABLE declaraciones (id INTEGER PRIMARY KEY AUTOINCREMENT, fideicomiso_id TEXT NOT NULL, periodo TEXT NOT NULL,
        estado TEXT NOT NULL, intentos INTEGER NOT NULL DEFAULT 0, detalle TEXT, ejecucion_id INTEGER,
        actualizado TEXT NOT NULL, UNIQUE (fideicomiso_id, periodo));
    CREATE TABLE eventos (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, ejecucion_id INTEGER,
        fideicomiso_id TEXT, periodo TEXT, estado TEXT, detalle TEXT);
    INSERT INTO ejecuciones (inicio, version, dry_run, hasta, periodo, usuario) VALUES ('2026-11-06T10:00:00','0.1.0',0,'contador','2026-10','u');
    INSERT INTO declaraciones (id, fideicomiso_id, periodo, estado, intentos, detalle, ejecucion_id, actualizado)
        VALUES (5,'142','2026-10','declarado',1,'comprobante serie 111',1,'2026-11-06T10:05:00'),
               (9,'7','2026-10','simulado',2,'',1,'2026-11-06T10:06:00');
    INSERT INTO eventos (ts, ejecucion_id, fideicomiso_id, periodo, estado, detalle)
        VALUES ('2026-11-06T10:05:00',1,'142','2026-10','declarado','x'),('2026-11-06T10:06:00',1,'7','2026-10','simulado','');
    """)
    con.commit()
    con.close()


def _filas(ruta):
    con = sqlite3.connect(str(ruta))
    try:
        return con.execute("SELECT fideicomiso_id, periodo, impuesto, estado, intentos, detalle FROM declaraciones ORDER BY id").fetchall()
    finally:
        con.close()


def _respaldos(carpeta):
    return sorted(carpeta.glob("*.pre_migracion_*"))


def test_una_base_antigua_se_migra_conservando_todo_y_deja_respaldo(tmp_path):
    ruta = tmp_path / "execution_history.db"
    _base_antigua(ruta)
    Repositorio(ruta).cerrar()
    assert _filas(ruta) == [("142", "2026-10", "2011", "declarado", 1, "comprobante serie 111"),
                            ("7", "2026-10", "2011", "simulado", 2, "")]
    con = sqlite3.connect(str(ruta))
    assert con.execute("PRAGMA user_version").fetchone()[0] == repository.VERSION_ESQUEMA
    assert con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0] == 2
    assert con.execute("SELECT DISTINCT impuesto FROM eventos").fetchall() == [("2011",)]
    con.close()
    (respaldo,) = _respaldos(tmp_path)
    cb = sqlite3.connect(str(respaldo))
    assert "impuesto" not in [f[1] for f in cb.execute("PRAGMA table_info(declaraciones)")]  # conserva el esquema viejo
    assert cb.execute("SELECT COUNT(*) FROM declaraciones").fetchone()[0] == 2
    cb.close()


def test_tras_migrar_retenciones_del_mismo_fideicomiso_ya_no_choca_con_el_iva(tmp_path):
    ruta = tmp_path / "execution_history.db"
    _base_antigua(ruta)
    with Repositorio(ruta) as r:
        assert r.estado("142", TXT) == Estado.DECLARADO and r.estado("142", TXT, "1031") is None
        r.marcar("142", TXT, Estado.SIMULADO, impuesto="1031")
        assert r.estado("142", TXT) == Estado.DECLARADO and r.estado("142", TXT, "1031") == Estado.SIMULADO


def test_abrir_otra_vez_no_migra_ni_crea_otro_respaldo(tmp_path):
    ruta = tmp_path / "execution_history.db"
    _base_antigua(ruta)
    Repositorio(ruta).cerrar()
    antes = _filas(ruta)
    Repositorio(ruta).cerrar()
    assert _filas(ruta) == antes and len(_respaldos(tmp_path)) == 1


def test_una_base_nueva_no_genera_respaldos(tmp_path):
    ruta = tmp_path / "carpeta" / "execution_history.db"
    Repositorio(ruta).cerrar()
    assert _respaldos(ruta.parent) == [] and sqlite3.connect(str(ruta)).execute("PRAGMA user_version").fetchone()[0] == 2


def test_si_la_migracion_falla_la_base_queda_exactamente_como_estaba(tmp_path, monkeypatch):
    ruta = tmp_path / "execution_history.db"
    _base_antigua(ruta)

    def falla(con, antes):
        raise RuntimeError("fallo simulado a mitad de la migracion")
    monkeypatch.setattr(repository, "_verificar_migracion", falla)
    with pytest.raises(RuntimeError, match="fallo simulado"):
        Repositorio(ruta)
    con = sqlite3.connect(str(ruta))
    assert "impuesto" not in [f[1] for f in con.execute("PRAGMA table_info(declaraciones)")]
    assert con.execute("SELECT COUNT(*) FROM declaraciones").fetchone()[0] == 2
    assert "declaraciones_nueva" not in [t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    con.close()
    assert len(_respaldos(tmp_path)) == 1
    monkeypatch.undo()
    Repositorio(ruta).cerrar()  # y un intento posterior, ya sin el fallo, migra bien
    assert _filas(ruta)[0][2] == "2011"


def test_la_migracion_conserva_los_ids_para_no_romper_referencias(tmp_path):
    ruta = tmp_path / "execution_history.db"
    _base_antigua(ruta)
    Repositorio(ruta).cerrar()
    con = sqlite3.connect(str(ruta))
    assert [f[0] for f in con.execute("SELECT id FROM declaraciones ORDER BY id")] == [5, 9]  # no consecutivos a proposito
    con.close()


# ------------------------------------------------------------------ el orquestador respeta el impuesto
def test_un_lote_de_retenciones_no_se_confunde_con_el_iva_ni_al_reves():
    with Repositorio(":memory:") as r:
        r.marcar("1", TXT, Estado.DECLARADO)  # IVA ya declarado
        vistos = []
        procesar_lote([F("1")], P, r, lambda f: vistos.append(f.id), 1, estado_ok=Estado.SIMULADO, impuesto="1031")
        assert vistos == ["1"] and r.estado("1", TXT) == Estado.DECLARADO and r.estado("1", TXT, "1031") == Estado.SIMULADO
        r.marcar("2", TXT, Estado.DECLARADO, impuesto="1031")  # retenciones ya hechas
        procesar_lote([F("2")], P, r, lambda f: vistos.append(f.id), 2, estado_ok=Estado.SIMULADO)
        assert vistos == ["1", "2"] and r.estado("2", TXT) == Estado.SIMULADO and r.estado("2", TXT, "1031") == Estado.DECLARADO


def test_un_declarado_de_retenciones_no_se_repite():
    with Repositorio(":memory:") as r:
        r.marcar("1", TXT, Estado.DECLARADO, impuesto="1031")
        vistos = []
        res = procesar_lote([F("1")], P, r, lambda f: vistos.append(f.id), 1, estado_ok=Estado.SIMULADO, impuesto="1031")
        assert vistos == [] and res.omitidos == 1


# ------------------------------------------------------------------ el Control: RETENCION_0 tiene su propia lista
def _control(tmp_path, filas, con_retencion=True):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fideicomisos"
    ws.append(["ID", "NOMBRE", "RUC", "DECLARA_0"] + (["RETENCION_0"] if con_retencion else []) + ["RESPONSABLE"])
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def test_cada_impuesto_lee_su_propia_columna(tmp_path):
    ruta = _control(tmp_path, [["A", "a", "1790000000001", "SI", "NO", "x"], ["B", "b", "1790000000002", "NO", "SI", "x"],
                               ["C", "c", "1790000000003", "SI", "SI", "x"]])
    assert [p.id for p in leer_control(ruta).pendientes] == ["A", "C"]
    assert [p.id for p in leer_control(ruta, "retencion_0").pendientes] == ["B", "C"]


def test_retencion_0_aplica_las_mismas_validaciones(tmp_path):
    ruta = _control(tmp_path, [["A", "a", "1790000000001", "NO", "SI", "x"], ["A", "b", "1790000000002", "NO", "SI", "x"],
                               ["C", "c", "123", "NO", "X", "x"]])
    r = leer_control(ruta, "retencion_0")
    motivos = {e.fila: e.motivo for e in r.excluidos}
    assert "ID repetido" in motivos[2] and "ID repetido" in motivos[3]
    assert "RETENCION_0 con valor no reconocido" in motivos[4] and "RUC invalido" in motivos[4]


def test_un_control_sin_la_columna_nueva_sigue_sirviendo_para_el_iva(tmp_path):
    ruta = _control(tmp_path, [["A", "a", "1790000000001", "SI", "x"]], con_retencion=False)
    assert [p.id for p in leer_control(ruta).pendientes] == ["A"]
    with pytest.raises(ConfigError, match="retencion_0"):
        leer_control(ruta, "retencion_0")


def test_marca_desconocida():
    with pytest.raises(ConfigError, match="Marca desconocida"):
        leer_control(None, "otra")


# ------------------------------------------------------------------ main: lote de retenciones en modo prueba
def _fake_open_context(monkeypatch):
    @contextmanager
    def abrir():
        yield type("Ctx", (), {"pages": [], "new_page": lambda self: object()})()
    monkeypatch.setattr(main, "open_context", abrir)


def test_el_lote_de_retenciones_lee_retencion_0_y_usa_el_recorrido_de_retenciones(entorno, monkeypatch):
    llamadas, tmp = entorno
    marcas, recorridos = [], []
    fids = [Fideicomiso(2, "A1", "N", "1790000000001", "R"), Fideicomiso(3, "A2", "N", "1790000000002", "R")]
    monkeypatch.setattr(main, "leer_control", lambda _r, m="declara_0": marcas.append(m) or ResultadoControl(5, 3, fids, []))
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    _fake_open_context(monkeypatch)
    monkeypatch.setattr(retenciones, "recorrer", lambda ctx, page, cid, per, hasta, cred, cont, **kw: recorridos.append(cid))
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: llamadas["flujo"].append("iva"))
    assert main.main(["--lote", "--impuesto", "1031", "--hasta", "periodo", "--pausa", "0"]) == 0
    assert marcas == ["retencion_0"] and recorridos == ["A1", "A2"] and llamadas["flujo"] == []
    con = sqlite3.connect(str(tmp / "execution_history.db"))
    assert con.execute("SELECT fideicomiso_id, impuesto, estado FROM declaraciones ORDER BY id").fetchall() == [
        ("A1", "1031", "parcial"), ("A2", "1031", "parcial")]
    con.close()


def test_el_lote_de_iva_sigue_leyendo_declara_0_y_registra_2011(entorno, monkeypatch):
    llamadas, tmp = entorno
    marcas = []
    fids = [Fideicomiso(2, "A1", "N", "1790000000001", "R")]
    monkeypatch.setattr(main, "leer_control", lambda _r, m="declara_0": marcas.append(m) or ResultadoControl(5, 4, fids, []))
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    _fake_open_context(monkeypatch)
    monkeypatch.setattr(main, "_flujo", lambda ctx, page, cid, per, hasta, cred, cont, **kw: llamadas["flujo"].append(cid))
    assert main.main(["--lote", "--impuesto", "2011", "--hasta", "periodo", "--pausa", "0"]) == 0
    assert marcas == ["declara_0"] and llamadas["flujo"] == ["A1"]
    con = sqlite3.connect(str(tmp / "execution_history.db"))
    assert con.execute("SELECT impuesto FROM declaraciones").fetchall() == [("2011",)]
    con.close()


def test_los_dos_impuestos_en_el_mismo_periodo_quedan_como_filas_separadas(entorno, monkeypatch):
    llamadas, tmp = entorno
    fids = [Fideicomiso(2, "A1", "N", "1790000000001", "R")]
    monkeypatch.setattr(main, "leer_control", lambda _r, m="declara_0": ResultadoControl(5, 4, fids, []))
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    _fake_open_context(monkeypatch)
    monkeypatch.setattr(retenciones, "recorrer", lambda *a, **k: None)
    monkeypatch.setattr(main, "_flujo", lambda *a, **k: None)
    main.main(["--lote", "--impuesto", "2011", "--hasta", "periodo", "--pausa", "0"])
    main.main(["--lote", "--impuesto", "1031", "--hasta", "periodo", "--pausa", "0"])
    con = sqlite3.connect(str(tmp / "execution_history.db"))
    assert con.execute("SELECT impuesto FROM declaraciones ORDER BY impuesto").fetchall() == [("1031",), ("2011",)]
    con.close()


def test_un_recargo_deja_el_fideicomiso_en_revision_manual_sin_detener_el_lote():
    from src.utils.exceptions import RecargosInesperados

    def ejecutar(f):
        if f.id == "1":
            raise RecargosInesperados("multa 1.00")
    with Repositorio(":memory:") as r:
        res = procesar_lote([F("1"), F("2")], P, r, ejecutar, 1, estado_ok=Estado.SIMULADO)
        assert r.estado("1", TXT) == Estado.REVISION_MANUAL and r.estado("2", TXT) == Estado.SIMULADO
        assert res.detenido is None  # un solo fallo no detiene el lote: otros fideicomisos pueden estar en plazo