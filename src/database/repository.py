"""Estado de las declaraciones en SQLite. 'declaraciones' guarda el estado actual (una fila por fideicomiso y periodo,
lo que impide duplicados); 'eventos' es un registro de solo anexar con cada cambio, para auditoria."""
import sqlite3
from datetime import datetime
from pathlib import Path

from src.database.models import Estado
from src.utils.logger import redactar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, inicio TEXT NOT NULL, fin TEXT, version TEXT, dry_run INTEGER,
    hasta TEXT, periodo TEXT, usuario TEXT, resumen TEXT);
CREATE TABLE IF NOT EXISTS declaraciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fideicomiso_id TEXT NOT NULL, periodo TEXT NOT NULL,
    estado TEXT NOT NULL, intentos INTEGER NOT NULL DEFAULT 0, detalle TEXT, ejecucion_id INTEGER,
    actualizado TEXT NOT NULL, UNIQUE (fideicomiso_id, periodo));
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, ejecucion_id INTEGER, fideicomiso_id TEXT,
    periodo TEXT, estado TEXT, detalle TEXT);
"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, ruta):
        if str(ruta) != ":memory:":
            Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(ruta))
        self._db.executescript(ESQUEMA)

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

    def estado(self, fideicomiso_id: str, periodo: str):
        fila = self._db.execute("SELECT estado FROM declaraciones WHERE fideicomiso_id=? AND periodo=?",
                                (fideicomiso_id, periodo)).fetchone()
        return Estado(fila[0]) if fila else None

    def marcar(self, fideicomiso_id: str, periodo: str, estado: Estado, detalle: str = "",
               ejecucion_id: int | None = None, intento: bool = False) -> None:
        detalle = redactar(str(detalle))[:300]
        ahora, suma = _ahora(), int(intento)
        self._db.execute(
            """INSERT INTO declaraciones (fideicomiso_id, periodo, estado, intentos, detalle, ejecucion_id, actualizado)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (fideicomiso_id, periodo) DO UPDATE SET estado=excluded.estado,
                   intentos=intentos+?, detalle=excluded.detalle, ejecucion_id=excluded.ejecucion_id,
                   actualizado=excluded.actualizado""",
            (fideicomiso_id, periodo, estado.value, suma, detalle, ejecucion_id, ahora, suma))
        self._db.execute(
            "INSERT INTO eventos (ts, ejecucion_id, fideicomiso_id, periodo, estado, detalle) VALUES (?,?,?,?,?,?)",
            (ahora, ejecucion_id, fideicomiso_id, periodo, estado.value, detalle))
        self._db.commit()

    def recuperar_interrumpidas(self, periodo: str, ejecucion_id: int | None = None) -> int:
        """Una declaracion 'en_proceso' de una ejecucion anterior quedo a medias: no se sabe si llego a enviarse,
        asi que pasa a revision manual en lugar de reintentarse sola."""
        ids = [f[0] for f in self._db.execute(
            "SELECT fideicomiso_id FROM declaraciones WHERE periodo=? AND estado=?",
            (periodo, Estado.EN_PROCESO.value))]
        for fid in ids:
            self.marcar(fid, periodo, Estado.REVISION_MANUAL,
                        "ejecucion interrumpida: verificar en el SRI si se declaro", ejecucion_id)
        return len(ids)
