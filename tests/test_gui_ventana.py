"""Pruebas de la ventana real. Se saltan solas si no hay tkinter o no hay pantalla (p. ej. un servidor sin escritorio)."""
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

import zero_gui  # noqa: E402
from src.core import process_queue  # noqa: E402
from src.gui import ventana as v  # noqa: E402
from src.gui.puente import Puente  # noqa: E402
from src.gui.resumen import Resumen  # noqa: E402


@pytest.fixture(autouse=True)
def _limpiar_detener():
    process_queue.DETENER.clear()
    yield
    process_queue.DETENER.clear()


@pytest.fixture
def crear(monkeypatch):
    ventanas = []

    def _crear(correr_fn=None, dry_run=False, resumen=None):
        try:
            w = v.Ventana(resumen_fn=lambda: resumen or Resumen("10-2026", 2, 3, "OneDrive"),
                          correr_fn=correr_fn or (lambda argv, puente: puente.eventos.put(("fin", 0))), dry_run=dry_run,
                          periodo_fn=lambda: (2026, 10))
        except tk.TclError:
            pytest.skip("no hay pantalla disponible")
        w.withdraw()
        ventanas.append(w)
        return w
    yield _crear
    for w in ventanas:
        try:
            w.destroy()
        except tk.TclError:
            pass


def esperar(w, condicion, segundos=5):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        w.update()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def texto_registro(w):
    return w.registro.get("1.0", "end")


@pytest.fixture
def dialogos(monkeypatch):
    vistos = {"aviso": [], "info": [], "pregunta": []}
    monkeypatch.setattr(v.messagebox, "showwarning", lambda *a, **k: vistos["aviso"].append(a))
    monkeypatch.setattr(v.messagebox, "showinfo", lambda *a, **k: vistos["info"].append(a))
    vistos["respuesta"] = True

    def pregunta(titulo, texto, **k):
        vistos["pregunta"].append(texto)
        return vistos["respuesta"]
    monkeypatch.setattr(v.messagebox, "askyesno", pregunta)
    return vistos


# ---- cabecera ----

def test_la_cabecera_muestra_periodo_y_pendientes(crear):
    w = crear()
    assert esperar(w, lambda: w.v_iva.cget("text") == "2")
    assert w.v_periodo.cget("text") == "10-2026" and w.v_ret.cget("text") == "3" and w.v_con.cget("text") == "Conectado"


def test_el_periodo_se_ve_desde_el_primer_momento(crear):
    w = crear(resumen=Resumen("10-2026", error="HTTP 404"))
    assert w.v_periodo.cget("text") == "10-2026"  # antes de que llegue lo del Control


def test_si_no_se_lee_el_control_se_dice(crear):
    w = crear(resumen=Resumen("10-2026", error="HTTP 404"))
    assert esperar(w, lambda: w.v_con.cget("text") == "Sin conexion")
    assert "404" in w.p_con.cget("text") and w.v_iva.cget("text") == "-"


# ---- botones ----

def test_dry_run_bloquea_el_envio_real(crear):
    w = crear(dry_run=True)
    assert "disabled" in w.b_enviar.state() and "disabled" not in w.b_simular.state()
    assert "DRY_RUN" in w.aviso.cget("text")
    w2 = crear(dry_run=False)
    assert "disabled" not in w2.b_enviar.state()


def test_sin_contrasena_no_arranca(crear, dialogos):
    llamadas = []
    w = crear(correr_fn=lambda argv, puente: llamadas.append(argv))
    w.b_enviar.invoke()
    w.update()
    assert dialogos["aviso"] and not llamadas and not w._corriendo


@pytest.mark.parametrize("boton,argv", [("b_simular", ["--simular"]), ("b_enviar", [])])
def test_cada_boton_lanza_su_modo(crear, dialogos, boton, argv):
    llamadas = []

    def correr_falso(a, puente):
        llamadas.append(a)
        puente.eventos.put(("fin", 0))
    w = crear(correr_fn=correr_falso)
    w.clave.insert(0, "maestra")
    getattr(w, boton).invoke()
    assert esperar(w, lambda: llamadas and not w._corriendo)
    assert llamadas == [argv]


def test_mientras_corre_los_botones_se_bloquean_y_al_final_se_liberan(crear, dialogos):
    soltar = threading.Event()

    def correr_lento(argv, puente):
        puente.eventos.put(("salida", "Impuesto: 2011 (IVA) | marcados SI: 2 | listos: 2 | excluidos: 0"))
        puente.eventos.put(("log", "INFO", "Fideicomiso A1 -> declarado"))
        soltar.wait(5)
        puente.eventos.put(("log", "INFO", "Fideicomiso A2 -> error (PortalChanged)"))
        puente.eventos.put(("fin", 0))
    w = crear(correr_fn=correr_lento)
    w.clave.insert(0, "maestra")
    w.b_enviar.invoke()
    assert esperar(w, lambda: "Fideicomiso 2 de 2" in w.estado.cget("text"))
    assert all("disabled" in b.state() for b in (w.b_simular, w.b_enviar)) and "disabled" not in w.b_detener.state()
    assert "1 correctas" in w.conteo.cget("text")
    soltar.set()
    assert esperar(w, lambda: not w._corriendo)
    assert all("disabled" not in b.state() for b in (w.b_simular, w.b_enviar)) and "disabled" in w.b_detener.state()
    assert "1 con problema" in w.conteo.cget("text") and "Terminado" in w.estado.cget("text")
    assert w.clave.get() == ""  # la contrasena no se queda en la ventana
    assert "declarado" in texto_registro(w)


def test_con_dry_run_el_envio_sigue_bloqueado_despues_de_simular(crear, dialogos):
    def correr_falso(argv, puente):
        puente.eventos.put(("fin", 0))
    w = crear(dry_run=True, correr_fn=correr_falso)
    w.clave.insert(0, "maestra")
    w.b_simular.invoke()
    assert esperar(w, lambda: not w._corriendo)
    assert "disabled" in w.b_enviar.state() and "disabled" not in w.b_simular.state()


# ---- confirmacion y detener ----

def test_la_confirmacion_del_nucleo_sale_como_cuadro_de_dialogo(crear, dialogos):
    resultado = []

    def correr_pregunta(argv, puente):
        resultado.append(puente.input("Se ENVIARAN hasta 4 declaraciones REALES. Escriba SI: "))
        puente.eventos.put(("fin", 0))
    w = crear(correr_fn=correr_pregunta)
    w.clave.insert(0, "maestra")
    w.b_enviar.invoke()
    assert esperar(w, lambda: resultado)
    assert resultado == ["SI"]
    texto = dialogos["pregunta"][0]
    assert "10-2026" in texto and "ENVIARAN hasta 4" in texto and "Escriba" not in texto


def test_responder_no_en_el_dialogo_es_no(crear, dialogos):
    dialogos["respuesta"] = False
    resultado = []

    def correr_pregunta(argv, puente):
        resultado.append(puente.input("Confirma? Escriba SI: "))
        puente.eventos.put(("fin", 1))
    w = crear(correr_fn=correr_pregunta)
    w.clave.insert(0, "maestra")
    w.b_simular.invoke()
    assert esperar(w, lambda: resultado)
    assert resultado == ["NO"]


def test_detener_activa_la_senal_y_cancela_al_puente(crear, dialogos):
    capturado = {}
    esperando = threading.Event()

    def correr_largo(argv, puente):
        capturado["puente"] = puente
        esperando.set()
        while not process_queue.DETENER.is_set():
            time.sleep(0.01)
        puente.eventos.put(("fin", 3))
    w = crear(correr_fn=correr_largo)
    w.clave.insert(0, "maestra")
    w.b_simular.invoke()
    assert esperar(w, esperando.is_set)
    w.b_detener.invoke()
    assert process_queue.DETENER.is_set() and capturado["puente"]._cancelado.is_set()
    assert esperar(w, lambda: not w._corriendo)
    assert "Detenido" in w.estado.cget("text")


def test_no_se_puede_cerrar_mientras_corre(crear, dialogos):
    soltar = threading.Event()
    w = crear(correr_fn=lambda a, p: (soltar.wait(5), p.eventos.put(("fin", 0))))
    w.clave.insert(0, "maestra")
    w.b_simular.invoke()
    assert esperar(w, lambda: w._corriendo)
    w._cerrar()
    assert dialogos["info"] and w.winfo_exists()
    soltar.set()
    assert esperar(w, lambda: not w._corriendo)
    w._cerrar()
    with pytest.raises(tk.TclError):  # la ventana ya no existe
        w.winfo_exists()


def test_un_error_se_ve_en_el_registro(crear, dialogos):
    w = crear(correr_fn=lambda a, p: (p.eventos.put(("log", "ERROR", "ConfigError: falta algo")), p.eventos.put(("fin", 1))))
    w.clave.insert(0, "maestra")
    w.b_simular.invoke()
    assert esperar(w, lambda: not w._corriendo)
    assert "ConfigError: falta algo" in texto_registro(w) and "No se completo" in w.estado.cget("text")


# ---- punto de entrada ----

def test_si_la_ventana_no_arranca_se_muestra_el_error(monkeypatch):
    mostrados = []

    class Rota:
        def __init__(self):
            raise RuntimeError("no abre")
    monkeypatch.setattr(v, "Ventana", Rota)
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda t, d: mostrados.append(d))
    assert zero_gui.principal() == 2
    assert mostrados and "no abre" in mostrados[0]