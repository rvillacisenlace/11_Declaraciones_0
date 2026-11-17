"""Puente entre la ventana y el nucleo. NO usa tkinter: asi se prueba sin pantalla.

El nucleo (main.main) pide datos con input() y getpass.getpass(). Mientras corre desde la ventana, esas dos funciones se
sustituyen por las del Puente, que preguntan a la ventana (cuadros de dialogo) y esperan la respuesta. El nucleo no se toca.
"""
import builtins
import getpass
import io
import logging
import queue
import re
import sys
import threading
from dataclasses import dataclass, field

from src.core import process_queue
from src.utils.exceptions import ZeroError
from src.utils.logger import configurar_logging, redactar

CORRECTOS = {"declarado", "simulado", "parcial"}
OMITIDOS = {"ya_declarado", "obligacion_no_disponible"}
PROBLEMAS = {"error", "revision_manual"}


class Cancelado(ZeroError):
    """El operador cancelo una pregunta o detuvo la ejecucion."""


@dataclass
class Solicitud:
    tipo: str  # "confirmar" (respuesta bool) | "clave" (respuesta str)
    texto: str
    respuesta: object = None
    evento: threading.Event = field(default_factory=threading.Event)

    def responder(self, valor) -> None:
        self.respuesta = valor
        self.evento.set()


class Puente:
    def __init__(self, clave: str = ""):
        self.eventos: queue.Queue = queue.Queue()      # hilo de trabajo -> ventana
        self.solicitudes: queue.Queue = queue.Queue()  # preguntas al operador
        self._clave = clave
        self._cancelado = threading.Event()
        self._pendientes: list[Solicitud] = []
        self._cerrojo = threading.Lock()

    def cancelar(self) -> None:
        """Detiene: lo pendiente se cancela y toda pregunta posterior tambien."""
        self._cancelado.set()
        with self._cerrojo:
            for s in self._pendientes:
                s.evento.set()

    def _preguntar(self, tipo: str, texto: str):
        if self._cancelado.is_set():
            raise Cancelado("Ejecucion detenida por el operador")
        s = Solicitud(tipo, texto)
        with self._cerrojo:
            self._pendientes.append(s)
        self.solicitudes.put(s)
        s.evento.wait()
        with self._cerrojo:
            self._pendientes.remove(s)
        if self._cancelado.is_set() or s.respuesta is None:
            raise Cancelado("Operacion cancelada por el operador")
        return s.respuesta

    # Sustitutos de input() y getpass.getpass() ------------------------------------------------------------------
    def input(self, prompt: str = "") -> str:
        if "Escriba SI" in prompt:
            texto = prompt.replace("Escriba SI:", "").strip()
            return "SI" if self._preguntar("confirmar", texto) else "NO"
        raise ZeroError("Ese paso necesita la consola: use la version de linea de comandos")

    def getpass(self, prompt: str = "", stream=None) -> str:
        if self._clave:
            return self._clave
        self._clave = self._preguntar("clave", prompt.strip())
        return self._clave


class ManejadorLog(logging.Handler):
    """Lleva a la ventana lo que se escribe en el log (ya con los datos sensibles redactados)."""

    def __init__(self, eventos: queue.Queue):
        super().__init__(logging.INFO)
        self._eventos = eventos

    def emit(self, record: logging.LogRecord) -> None:
        texto = record.getMessage()
        if record.exc_info:
            texto += f" ({record.exc_info[0].__name__}; detalle en el log)"
        self._eventos.put(("log", record.levelname, redactar(texto)))


class EscritorSalida(io.TextIOBase):
    """Recoge lo que el nucleo imprime (resumenes por impuesto y responsable) linea por linea."""

    def __init__(self, eventos: queue.Queue):
        self._eventos, self._resto = eventos, ""

    def writable(self) -> bool:
        return True

    def write(self, texto: str) -> int:
        self._resto += texto
        while "\n" in self._resto:
            linea, self._resto = self._resto.split("\n", 1)
            if linea.strip():
                self._eventos.put(("salida", redactar(linea.rstrip())))
        return len(texto)

    def vaciar(self) -> None:
        if self._resto.strip():
            self._eventos.put(("salida", redactar(self._resto.rstrip())))
        self._resto = ""


@dataclass
class Avance:
    """Progreso y conteo, leidos de lo que el nucleo ya informa (no hace falta tocarlo)."""
    total: int = 0
    hechos: int = 0
    correctas: int = 0
    omitidas: int = 0
    problemas: int = 0

    def registrar(self, evento: tuple) -> None:
        if evento[0] == "salida":
            m = re.search(r"\blistos: (\d+)", evento[1])
            if m:
                self.total += int(m.group(1))
        elif evento[0] == "log":
            m = re.match(r"Fideicomiso \S+ -> (\w+)", evento[2])
            if m:
                self.hechos += 1
                estado = m.group(1)
                if estado in CORRECTOS:
                    self.correctas += 1
                elif estado in OMITIDOS:
                    self.omitidas += 1
                elif estado in PROBLEMAS:
                    self.problemas += 1


def correr(argv: list[str], puente: Puente, funcion=None) -> int:
    """Ejecuta el nucleo con la interaccion redirigida al puente. Pensado para un hilo aparte; siempre termina
    enviando ('fin', codigo) y deja input, getpass, stdout, stderr y el log como estaban."""
    manejador = escritor = None
    previos = (builtins.input, getpass.getpass, sys.stdout, sys.stderr)
    codigo = 2
    raiz = logging.getLogger()
    nivel_previo = raiz.level
    try:
        if funcion is None:
            import main
            funcion = main.main
        configurar_logging()  # antes de redirigir: su StreamHandler debe quedar atado al flujo original
        process_queue.DETENER.clear()
        manejador, escritor = ManejadorLog(puente.eventos), EscritorSalida(puente.eventos)
        raiz.addHandler(manejador)
        if not raiz.level or raiz.level > logging.INFO:
            raiz.setLevel(logging.INFO)  # la ventana muestra el avance (INFO) aunque el log estuviera mas callado
        builtins.input, getpass.getpass = puente.input, puente.getpass
        sys.stdout = sys.stderr = escritor
        codigo = funcion(argv)
    except SystemExit as e:
        codigo = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Cancelado:
        codigo = 1
        puente.eventos.put(("log", "WARNING", "Ejecucion detenida por el operador"))
    except Exception as e:
        codigo = 2
        puente.eventos.put(("log", "ERROR", f"Error inesperado ({type(e).__name__}); detalle en el log"))
        logging.getLogger("zero").exception("Error inesperado en la ventana")
    finally:
        builtins.input, getpass.getpass, sys.stdout, sys.stderr = previos
        raiz.setLevel(nivel_previo)
        if manejador:
            raiz.removeHandler(manejador)
        if escritor:
            escritor.vaciar()
        puente.eventos.put(("fin", codigo))
    return codigo
