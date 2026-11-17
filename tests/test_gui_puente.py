import builtins
import getpass
import logging
import sys
import threading

import pytest

import main
from src.core import process_queue
from src.gui import puente as p
from src.gui.puente import Avance, Cancelado, Puente, correr
from src.gui.resumen import calcular_resumen
from src.services import fideicomiso_service
from src.utils.exceptions import GraphError, ZeroError
from src.database.repository import Repositorio
from tests.test_main_lote import entorno  # noqa: F401  (fixture reutilizada)


def _estado(tmp_path, fid):
    with Repositorio(tmp_path / "execution_history.db") as r:
        e = r.estado(fid, "2026-10")
        return e.value if e else None


_AYUDANTES = []


@pytest.fixture(autouse=True)
def _limpiar_detener():
    process_queue.DETENER.clear()
    yield
    process_queue.DETENER.clear()
    while _AYUDANTES:  # ningun hilo auxiliar sobrevive al test
        hilo, puente = _AYUDANTES.pop()
        puente.solicitudes.put(None)
        hilo.join(timeout=5)


def _contestar(puente, respuestas):
    """Hace de ventana: contesta cada pregunta del nucleo con lo indicado (por tipo)."""
    def bucle():
        while True:
            s = puente.solicitudes.get()
            if s is None:
                return
            s.responder(respuestas[s.tipo])
    t = threading.Thread(target=bucle, daemon=True)
    t.start()
    _AYUDANTES.append((t, puente))
    return t


def _eventos(puente):
    salida = []
    while not puente.eventos.empty():
        salida.append(puente.eventos.get_nowait())
    return salida


# ---- preguntas del nucleo ----

def test_confirmar_si_y_no():
    puente = Puente("x")
    _contestar(puente, {"confirmar": True})
    assert puente.input("Se ENVIARAN 4 declaraciones. Escriba SI: ") == "SI"
    puente2 = Puente("x")
    _contestar(puente2, {"confirmar": False})
    assert puente2.input("Confirma? Escriba SI: ") == "NO"


def test_la_pregunta_llega_sin_el_escriba_si():
    puente = Puente("x")
    puente.input  # noqa: B018
    hilo = threading.Thread(target=lambda: puente.input("Se ENVIARAN 4. Escriba SI: "), daemon=True)
    hilo.start()
    s = puente.solicitudes.get(timeout=5)
    assert s.tipo == "confirmar" and s.texto == "Se ENVIARAN 4." and "Escriba" not in s.texto
    s.responder(True)
    hilo.join(5)


def test_otras_preguntas_de_consola_no_se_admiten():
    with pytest.raises(ZeroError, match="consola"):
        Puente("x").input("RUC del contador: ")


def test_la_clave_ya_escrita_no_se_vuelve_a_pedir():
    puente = Puente("maestra")
    assert puente.getpass("Contrasena: ") == "maestra" and puente.solicitudes.empty()


def test_sin_clave_se_pregunta_una_vez():
    puente = Puente("")
    _contestar(puente, {"clave": "escrita"})
    assert puente.getpass("Contrasena del archivo: ") == "escrita"
    assert puente.getpass("otra vez") == "escrita"  # no pregunta de nuevo


def test_cerrar_el_cuadro_de_clave_cancela():
    puente = Puente("")
    _contestar(puente, {"clave": None})
    with pytest.raises(Cancelado):
        puente.getpass("Contrasena: ")


def test_cancelar_libera_al_nucleo_que_esperaba():
    puente = Puente("x")
    resultado = []

    def nucleo():
        try:
            puente.input("Confirma? Escriba SI: ")
        except Cancelado:
            resultado.append("cancelado")
    hilo = threading.Thread(target=nucleo, daemon=True)
    hilo.start()
    puente.solicitudes.get(timeout=5)
    puente.cancelar()
    hilo.join(5)
    assert resultado == ["cancelado"]


def test_tras_cancelar_ninguna_pregunta_se_hace():
    puente = Puente("")
    puente.cancelar()
    with pytest.raises(Cancelado):
        puente.input("Confirma? Escriba SI: ")
    assert puente.solicitudes.empty()


# ---- correr() ----

def test_correr_restaura_todo_y_avisa_el_fin():
    puente = Puente("x")
    antes = (builtins.input, getpass.getpass, sys.stdout, sys.stderr, list(logging.getLogger().handlers),
             logging.getLogger().level)

    def funcion(argv):
        print("linea impresa")
        logging.getLogger("zero").info("mensaje de log")
        assert builtins.input == puente.input and getpass.getpass == puente.getpass
        return 0
    assert correr([], puente, funcion) == 0
    assert (builtins.input, getpass.getpass, sys.stdout, sys.stderr, list(logging.getLogger().handlers),
            logging.getLogger().level) == antes
    ev = _eventos(puente)
    assert ("salida", "linea impresa") in ev and ("log", "INFO", "mensaje de log") in ev and ev[-1] == ("fin", 0)


def test_correr_restaura_aunque_el_nucleo_reviente():
    puente = Puente("x")
    antes = (builtins.input, getpass.getpass, sys.stdout)

    def funcion(argv):
        raise ValueError("detalle secreto")
    assert correr([], puente, funcion) == 2
    assert (builtins.input, getpass.getpass, sys.stdout) == antes
    ev = _eventos(puente)
    assert ev[-1] == ("fin", 2) and any("ValueError" in e[2] for e in ev if e[0] == "log")
    assert not any("detalle secreto" in str(e) for e in ev)


@pytest.mark.parametrize("sale,esperado", [(2, 2), (None, 0), ("x", 1)])
def test_correr_systemexit(sale, esperado):
    def funcion(argv):
        raise SystemExit(sale)
    assert correr([], Puente("x"), funcion) == esperado


def test_correr_cancelado_da_1():
    puente = Puente("x")

    def funcion(argv):
        raise Cancelado("x")
    assert correr([], puente, funcion) == 1
    assert any("detenida" in e[2] for e in _eventos(puente) if e[0] == "log")


def test_los_datos_sensibles_se_redactan_antes_de_mostrarse():
    puente = Puente("x")

    def funcion(argv):
        logging.getLogger("zero").info("RUC 1790000000001 clave=abc123")
        print("RUC 1790000000001")
        return 0
    correr([], puente, funcion)
    texto = str(_eventos(puente))
    assert "1790000000001" not in texto and "abc123" not in texto and "1790" in texto


# ---- Avance ----

def test_avance_lee_total_y_estados():
    a = Avance()
    a.registrar(("salida", "Impuesto: 2011 (IVA) | marcados SI: 3 | listos: 2 | excluidos: 1"))
    a.registrar(("salida", "Impuesto: 1031 (Retenciones) | marcados SI: 2 | listos: 2 | excluidos: 0"))
    for ev in ("Fideicomiso A1 -> declarado", "Fideicomiso A2 -> ya_declarado", "Fideicomiso A3 -> error (PortalChanged)",
               "Fideicomiso A4 -> revision_manual (EnvioIncierto)", "Lote terminado: procesados=4", "Otra cosa"):
        a.registrar(("log", "INFO", ev))
    assert (a.total, a.hechos, a.correctas, a.omitidas, a.problemas) == (4, 4, 1, 1, 2)


# ---- nucleo real a traves del puente ----

def test_el_nucleo_corre_con_el_puente(entorno, monkeypatch):  # noqa: F811
    llamadas, tmp = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    puente = Puente("maestra")
    monkeypatch.setattr(builtins, "input", lambda *_: pytest.fail("el nucleo uso el input real"))
    monkeypatch.setattr(main.getpass, "getpass", lambda *_: pytest.fail("el nucleo uso el getpass real"))
    _contestar(puente, {"confirmar": True})
    assert correr(["--lote", "--impuesto", "2011", "--hasta", "contador", "--pausa", "0"], puente) == 0
    ev = _eventos(puente)
    assert ev[-1][0] == "fin"
    a = Avance()
    for e in ev:
        a.registrar(e)
    assert llamadas["flujo"] == ["A1", "A2", "A3"]
    assert (a.total, a.hechos, a.correctas, a.problemas) == (3, 3, 3, 0)


def test_si_el_operador_dice_no_no_se_procesa_nada(entorno, monkeypatch):  # noqa: F811
    llamadas, _ = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    puente = Puente("maestra")
    _contestar(puente, {"confirmar": False})
    assert correr(["--lote", "--impuesto", "2011", "--hasta", "contador", "--pausa", "0"], puente) == 1
    assert llamadas["flujo"] == []


def test_detener_para_antes_de_la_siguiente_declaracion(entorno, monkeypatch):  # noqa: F811
    llamadas, tmp = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))

    def flujo(ctx, page, cid, per, hasta, cred, cont, **kw):
        llamadas["flujo"].append(cid)
        process_queue.DETENER.set()  # el operador pulsa Detener durante la primera
    monkeypatch.setattr(main, "_flujo", flujo)
    puente = Puente("maestra")
    _contestar(puente, {"confirmar": True})
    assert correr(["--lote", "--impuesto", "2011", "--hasta", "contador", "--pausa", "0"], puente) == 3
    assert llamadas["flujo"] == ["A1"]
    assert _estado(tmp, "A1") == "simulado" and _estado(tmp, "A2") is None and _estado(tmp, "A3") is None


# ---- cabecera ----

class _Hoja:
    def __init__(self, n):
        self.n = n


def test_resumen_cuenta_los_marcados(monkeypatch):
    monkeypatch.setattr(fideicomiso_service, "ruta_control", lambda: _Hoja(0))
    monkeypatch.setattr(fideicomiso_service, "leer_control",
                        lambda ruta, marca: type("R", (), {"pendientes": [1] * (2 if marca == "declara_0" else 5)})())
    r = calcular_resumen()
    assert (r.iva, r.retenciones, r.error, r.origen) == (2, 5, None, "Archivo local")


def test_resumen_desde_graph_y_con_errores(monkeypatch):
    hoja = type("G", (), {"leer_filas": lambda self: []})()
    monkeypatch.setattr(fideicomiso_service, "ruta_control", lambda: hoja)
    monkeypatch.setattr(fideicomiso_service, "leer_control", lambda ruta, marca: type("R", (), {"pendientes": []})())
    assert calcular_resumen().origen == "OneDrive"

    def falla(*a):
        raise GraphError("sin red")
    monkeypatch.setattr(fideicomiso_service, "leer_control", falla)
    assert calcular_resumen().error == "sin red"

    def rara(*a):
        raise KeyError("contenido privado")
    monkeypatch.setattr(fideicomiso_service, "leer_control", rara)
    r = calcular_resumen()
    assert "KeyError" in r.error and "privado" not in r.error


def test_una_detencion_anterior_no_bloquea_la_siguiente_ejecucion(entorno, monkeypatch):  # noqa: F811
    llamadas, _ = entorno
    monkeypatch.setattr(main, "periodo_a_declarar", lambda: (2026, 10))
    process_queue.DETENER.set()  # quedo activada por una ejecucion anterior
    puente = Puente("maestra")
    _contestar(puente, {"confirmar": True})
    assert correr(["--lote", "--impuesto", "2011", "--hasta", "contador", "--pausa", "0"], puente) == 0
    assert llamadas["flujo"] == ["A1", "A2", "A3"]
