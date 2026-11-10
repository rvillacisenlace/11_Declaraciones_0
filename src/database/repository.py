"""Estado de las declaraciones en SQLite. 'declaraciones' guarda el estado actual (una fila por fideicomiso, periodo
e IMPUESTO, lo que impide duplicados); 'eventos' es un registro de solo anexar con cada cambio, para auditoria.
Esquema version 2: agrega 'impuesto' (2011 = IVA, 1031 = retenciones). Una base anterior se migra sola, con copia de
seguridad previa y dentro de una transaccion: si algo falla, queda exactamente como estaba."""
import sqlite3
from datetime import datetime
from pathlib import Path

from src.database.models import Estado
from src.utils.logger import get_logger, redactar

log = get_logger(__name__)

VERSION_ESQUEMA = 2

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT NOT NULL, fin TEXT, version TEXT, dry_run INTEGER,
    hasta TEXT, periodo TEXT, usuario TEXT, resumen TEXT);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, ejecucion_id INTEGER, fideicomiso_id TEXT,
    periodo TEXT, impuesto TEXT NOT NULL DEFAULT '2011', estado TEXT, detalle TEXT);
"""


def _sql_declaraciones(nombre: str) -> str:
    return f"""CREATE TABLE {nombre} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fideicomiso_id TEXT NOT NULL, periodo TEXT NOT NULL,
    impuesto TEXT NOT NULL DEFAULT '2011', estado TEXT NOT NULL, intentos INTEGER NOT NULL DEFAULT 0,
    detalle TEXT, ejecucion_id INTEGER, actualizado TEXT NOT NULL, UNIQUE (fideicomiso_id, periodo, impuesto))"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _columnas(con, tabla: str) -> list[str]:
    return [f[1] for f in con.execute(f"PRAGMA table_info({tabla})")]


def _verificar_migracion(con, filas_antes: int) -> None:
    filas_despues = con.execute("SELECT COUNT(*) FROM declaraciones").fetchone()[0]
    if filas_despues != filas_antes:
        raise RuntimeError(f"La migracion perdio filas: {filas_antes} antes, {filas_despues} despues")


def _migrar_si_hace_falta(ruta: Path) -> None:
    if not ruta.exists() or ruta.stat().st_size == 0:
        return
    con = sqlite3.connect(str(ruta), isolation_level=None)  # transacciones manejadas a mano
    try:
        columnas = _columnas(con, "declaraciones")
        if not columnas or "impuesto" in columnas:
            return  # no existe todavia o ya esta migrada
        respaldo = ruta.with_name(f"{ruta.stem}.pre_migracion_{datetime.now():%Y%m%d%H%M%S}{ruta.suffix}")
        destino = sqlite3.connect(str(respaldo))
        try:
            con.backup(destino)
        finally:
            destino.close()
        log.warning("Migrando la base al esquema v%d. Copia de seguridad: %s", VERSION_ESQUEMA, respaldo.name)
        con.execute("BEGIN IMMEDIATE")
        try:
            antes = con.execute("SELECT COUNT(*) FROM declaraciones").fetchone()[0]
            con.execute(_sql_declaraciones("declaraciones_nueva"))
            con.execute("""INSERT INTO declaraciones_nueva
                (id, fideicomiso_id, periodo, impuesto, estado, intentos, detalle, ejecucion_id, actualizado)
                SELECT id, fideicomiso_id, periodo, '2011', estado, intentos, detalle, ejecucion_id, actualizado
                FROM declaraciones""")
            con.execute("DROP TABLE declaraciones")
            con.execute("ALTER TABLE declaraciones_nueva RENAME TO declaraciones")
            cols_eventos = _columnas(con, "eventos")
            if cols_eventos and "impuesto" not in cols_eventos:
                con.execute("ALTER TABLE eventos ADD COLUMN impuesto TEXT NOT NULL DEFAULT '2011'")
            _verificar_migracion(con, antes)
            con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        log.info("Migracion terminada: %d declaraciones conservadas (todas pasan a impuesto 2011)", antes)
    finally:
        con.close()


class Repositorio:
    def __init__(self, ruta):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
            _migrar_si_hace_falta(Path(ruta))
        self._db = sqlite3.connect(str(ruta))
        self._db.executescript(ESQUEMA)
        self._db.execute(_sql_declaraciones("IF NOT EXISTS declaraciones"))
        self._db.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        self._db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    def cerrar(self) -> None:
        self._db.close()

    def iniciar_ejecucion(self, version: str, dry_run: bool, hasta: str, periodo: str, usuario: str) -> int:
        cur = self._db.execute(
            "INSERT INTO ejecuciones (inicio, version, dry_run, hasta, periodo, usuario) VALUES (?,?,?,?,?,?)",
            (_ahora(), version, int(dry_run), hasta, periodo, usuario))
        self._db.commit()
        return cur.lastrowid

    def cerrar_ejecucion(self, ejecucion_id: int, resumen: str) -> None:
        self._db.execute("UPDATE ejecuciones SET fin=?, resumen=? WHERE id=?",
                         (_ahora(), redactar(resumen)[:500], ejecucion_id))
        self._db.commit()

    def estado(self, fideicomiso_id: str, periodo: str, impuesto: str = "2011"):
        fila = self._db.execute(
            "SELECT estado FROM declaraciones WHERE fideicomiso_id=? AND periodo=? AND impuesto=?",
            (fideicomiso_id, periodo, impuesto)).fetchone()
        return Estado(fila[0]) if fila else None

    def marcar(self, fideicomiso_id: str, periodo: str, estado: Estado, detalle: str = "",
               ejecucion_id: int | None = None, intento: bool = False, impuesto: str = "2011") -> None:
        detalle = redactar(str(detalle))[:300]
        ahora, suma = _ahora(), int(intento)
        self._db.execute(
            """INSERT INTO declaraciones
                   (fideicomiso_id, periodo, impuesto, estado, intentos, detalle, ejecucion_id, actualizado)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT (fideicomiso_id, periodo, impuesto) DO UPDATE SET estado=excluded.estado,
                   intentos=intentos+?, detalle=excluded.detalle, ejecucion_id=excluded.ejecucion_id,
                   actualizado=excluded.actualizado""",
            (fideicomiso_id, periodo, impuesto, estado.value, suma, detalle, ejecucion_id, ahora, suma))
        self._db.execute(
            "INSERT INTO eventos (ts, ejecucion_id, fideicomiso_id, periodo, impuesto, estado, detalle) "
            "VALUES (?,?,?,?,?,?,?)",
            (ahora, ejecucion_id, fideicomiso_id, periodo, impuesto, estado.value, detalle))
        self._db.commit()

    def recuperar_interrumpidas(self, periodo: str, ejecucion_id: int | None = None) -> int:
        """Una declaracion 'en_proceso' de una ejecucion anterior (de CUALQUIER impuesto) quedo a medias: no se sabe
        si llego a enviarse, asi que pasa a revision manual en lugar de reintentarse sola."""
        filas = list(self._db.execute(
            "SELECT fideicomiso_id, impuesto FROM declaraciones WHERE periodo=? AND estado=?",
            (periodo, Estado.EN_PROCESO.value)))
        for fid, impuesto in filas:
            self.marcar(fid, periodo, Estado.REVISION_MANUAL,
                        "ejecucion interrumpida: verificar en el SRI si se declaro", ejecucion_id, impuesto=impuesto)
        return len(filas)