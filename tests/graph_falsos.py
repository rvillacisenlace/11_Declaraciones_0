"""Dobles de prueba de Microsoft Graph: ninguna prueba toca la red ni un tenant real."""
import re

from openpyxl.utils import column_index_from_string, get_column_letter


class RespuestaFalsa:
    def __init__(self, status=200, cuerpo=None, contenido=b"", cabeceras=None):
        self.status_code = status
        self._cuerpo = cuerpo
        self.content = contenido
        self.headers = cabeceras or {}

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin cuerpo JSON")
        return self._cuerpo


class SesionFalsa:
    """Entrega las respuestas (o lanza las excepciones) en orden y guarda cada llamada."""

    def __init__(self, *respuestas):
        self._respuestas = list(respuestas)
        self.llamadas = []

    def request(self, metodo, url, headers=None, json=None, timeout=None):
        self.llamadas.append({"metodo": metodo, "url": url, "headers": headers, "json": json, "timeout": timeout})
        r = self._respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class AutenticacionFalsa:
    def __init__(self):
        self.renovaciones = 0
        self.emitidos = 0

    def token(self):
        self.emitidos += 1
        return f"token-{self.emitidos + self.renovaciones}"

    def renovar(self):
        self.renovaciones += 1


class ClienteControlFalso:
    """Imita la hoja 'Fideicomisos' de Graph: usedRange, lectura/escritura de una celda y descarga del archivo."""

    def __init__(self, filas, origen="A1", contenido=b"libro-original", ignorar_escritura=False):
        self.filas = [list(f) for f in filas]
        self.origen = origen
        self.contenido = contenido
        self.ignorar_escritura = ignorar_escritura
        self.llamadas = []

    def _origen(self):
        m = re.match(r"([A-Z]+)(\d+)", self.origen)
        return column_index_from_string(m.group(1)), int(m.group(2))

    def _celda(self, ruta):
        m = re.search(r"range\(address='([A-Z]+)(\d+)'\)", ruta)
        c0, f0 = self._origen()
        return int(m.group(2)) - f0, column_index_from_string(m.group(1)) - c0

    def get_json(self, ruta, *, contexto):
        self.llamadas.append(("GET", ruta))
        if ruta.endswith("/usedRange"):
            c0, f0 = self._origen()
            ancho = max((len(f) for f in self.filas), default=1)
            fin = f"{get_column_letter(c0 + ancho - 1)}{f0 + max(len(self.filas), 1) - 1}"
            return {"address": f"Fideicomisos!{self.origen}:{fin}", "values": self.filas}
        i, j = self._celda(ruta)
        return {"values": [[self.filas[i][j]]]}

    def patch_json(self, ruta, cuerpo, *, contexto):
        self.llamadas.append(("PATCH", ruta, cuerpo))
        if not self.ignorar_escritura:
            i, j = self._celda(ruta)
            self.filas[i][j] = cuerpo["values"][0][0]
        return {}

    def descargar(self, ruta, *, contexto):
        self.llamadas.append(("DESCARGA", ruta))
        return self.contenido

    def escrituras(self):
        return [x for x in self.llamadas if x[0] == "PATCH"]

    def descargas(self):
        return [x for x in self.llamadas if x[0] == "DESCARGA"]
