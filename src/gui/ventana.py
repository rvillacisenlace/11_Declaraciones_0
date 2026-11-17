"""Ventana de Zero (tkinter, viene con Python). Toda la logica vive en puente.py y resumen.py; aqui solo hay widgets.

El trabajo corre en un hilo aparte (Playwright es bloqueante) y la ventana lo consulta cada 100 ms: tkinter solo se toca
desde el hilo principal.
"""
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from config import settings
from src.core import process_queue
from src.gui.puente import Avance, Puente, correr
from src.gui.resumen import calcular_resumen
from src.utils.validators import periodo_a_declarar

FIN = {0: "Terminado sin problemas", 1: "No se completo: revise el registro", 2: "Error inesperado: revise el registro",
       3: "Detenido: revise el registro"}


class Ventana(tk.Tk):
    def __init__(self, *, resumen_fn=calcular_resumen, correr_fn=correr, dry_run=None, periodo_fn=periodo_a_declarar):
        super().__init__()
        self._resumen_fn, self._correr_fn = resumen_fn, correr_fn
        anio, mes = periodo_fn()  # no depende de la red: la confirmacion lo muestra siempre
        self._dry_run = settings.DRY_RUN if dry_run is None else dry_run
        self._puente: Puente | None = None
        self._avance = Avance()
        self._corriendo = False
        self._periodo = f"{mes:02d}-{anio}"
        self.title(f"Zero {settings.VERSION} - Declaraciones en cero")
        self.geometry("820x640")
        self.minsize(720, 520)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self._construir()
        self.v_periodo.config(text=self._periodo)
        self._bombear()
        self._actualizar_resumen()

    # ---- construccion -------------------------------------------------------------------------------------
    def _tarjeta(self, padre, titulo):
        marco = ttk.LabelFrame(padre, text=titulo, padding=(10, 4))
        valor = ttk.Label(marco, text="...", font=("Segoe UI", 16, "bold"))
        valor.pack(anchor="w")
        pie = ttk.Label(marco, text="", foreground="#555555")
        pie.pack(anchor="w")
        return marco, valor, pie

    def _construir(self):
        raiz = ttk.Frame(self, padding=14)
        raiz.pack(fill="both", expand=True)

        tarjetas = ttk.Frame(raiz)
        tarjetas.pack(fill="x")
        self._t_periodo, self.v_periodo, _ = self._tarjeta(tarjetas, "Periodo a declarar")
        self._t_iva, self.v_iva, _ = self._tarjeta(tarjetas, "IVA (2011) marcados SI")
        self._t_ret, self.v_ret, _ = self._tarjeta(tarjetas, "Retenciones (1031) marcados SI")
        self._t_con, self.v_con, self.p_con = self._tarjeta(tarjetas, "Control")
        for i, t in enumerate((self._t_periodo, self._t_iva, self._t_ret, self._t_con)):
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            tarjetas.columnconfigure(i, weight=1)

        ttk.Label(raiz, text="Contrasena del archivo de credenciales").pack(anchor="w", pady=(14, 2))
        self.clave = ttk.Entry(raiz, show="•", width=40)
        self.clave.pack(anchor="w")

        botones = ttk.Frame(raiz)
        botones.pack(anchor="w", pady=12)
        self.b_simular = ttk.Button(botones, text="Simular (no envia nada)", command=lambda: self._iniciar("simular"))
        self.b_enviar = ttk.Button(botones, text="Ejecutar y enviar", command=lambda: self._iniciar("enviar"))
        self.b_detener = ttk.Button(botones, text="Detener", command=self._detener, state="disabled")
        for b in (self.b_simular, self.b_enviar, self.b_detener):
            b.pack(side="left", padx=(0, 8))
        self.aviso = ttk.Label(raiz, text="", foreground="#b3261e")
        self.aviso.pack(anchor="w")
        if self._dry_run:
            self.b_enviar.state(["disabled"])
            self.aviso.config(text="DRY_RUN=true en el .env: el envio real esta bloqueado (solo simulacion).")

        self.estado = ttk.Label(raiz, text="Listo")
        self.estado.pack(anchor="w", pady=(4, 2))
        self.barra = ttk.Progressbar(raiz, mode="determinate", maximum=1)
        self.barra.pack(fill="x")

        zona = ttk.Frame(raiz)
        zona.pack(fill="both", expand=True, pady=(8, 4))
        self.registro = tk.Text(zona, height=10, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10), state="disabled",
                                wrap="word", borderwidth=0, padx=8, pady=6)
        scroll = ttk.Scrollbar(zona, command=self.registro.yview)
        self.registro.config(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.registro.pack(side="left", fill="both", expand=True)
        for nombre, color in (("ok", "#6fcf8a"), ("warn", "#e6c35c"), ("err", "#f28b82"), ("hora", "#8a8a8a")):
            self.registro.tag_config(nombre, foreground=color)

        pie = ttk.Frame(raiz)
        pie.pack(fill="x")
        ttk.Label(pie, text=f"Zero {settings.VERSION}  |  Comprobantes y evidencias: {settings.DECLARACIONES_DIR.parent}",
                  foreground="#555555").pack(side="left")
        self.conteo = ttk.Label(pie, text="", foreground="#555555")
        self.conteo.pack(side="right")

    # ---- cabecera -----------------------------------------------------------------------------------------
    def _actualizar_resumen(self):
        def trabajo():
            self._resumen_listo = self._resumen_fn()
        self._resumen_listo = None
        threading.Thread(target=trabajo, daemon=True).start()
        self.after(150, self._pintar_resumen)

    def _pintar_resumen(self):
        r = self._resumen_listo
        if r is None:
            self.after(150, self._pintar_resumen)
            return
        if r.error:
            self.v_iva.config(text="-")
            self.v_ret.config(text="-")
            self.v_con.config(text="Sin conexion", foreground="#b3261e")
            self.p_con.config(text=r.error[:60])
        else:
            self.v_iva.config(text=str(r.iva))
            self.v_ret.config(text=str(r.retenciones))
            self.v_con.config(text="Conectado" if r.origen == "OneDrive" else "Archivo local", foreground="#1c7c3a")
            self.p_con.config(text=f"{r.origen}: leido")

    # ---- ejecucion ----------------------------------------------------------------------------------------
    def _iniciar(self, modo):
        if self._corriendo:
            return
        clave = self.clave.get()
        if not clave:
            messagebox.showwarning("Zero", "Escriba la contrasena del archivo de credenciales.", parent=self)
            self.clave.focus_set()
            return
        argv = ["--simular"] if modo == "simular" else []
        self._puente, self._avance, self._corriendo = Puente(clave), Avance(), True
        self._botones(False)
        self.barra.config(mode="indeterminate")
        self.barra.start(12)
        self.estado.config(text="Preparando...")
        self.conteo.config(text="")
        self._escribir(f"--- {'Simulacion' if modo == 'simular' else 'Ejecucion con envio'} ---", "hora")
        puente = self._puente
        threading.Thread(target=self._trabajo, args=(argv, puente), daemon=True).start()

    def _trabajo(self, argv, puente):
        self._correr_fn(argv, puente)  # siempre deja un ('fin', codigo) en la cola, aunque falle

    def _detener(self):
        if self._corriendo and self._puente:
            process_queue.DETENER.set()
            self._puente.cancelar()
            self.b_detener.state(["disabled"])
            self.estado.config(text="Deteniendo: se para antes de la siguiente declaracion...")
            self._escribir("Se detendra antes de iniciar la siguiente declaracion.", "warn")

    def _botones(self, libres: bool):
        self.b_simular.state(["!disabled"] if libres else ["disabled"])
        self.b_enviar.state(["!disabled"] if libres and not self._dry_run else ["disabled"])
        self.b_detener.state(["disabled"] if libres else ["!disabled"])

    def _bombear(self):
        """Cada 100 ms: atiende preguntas del nucleo y pinta lo nuevo del registro."""
        p = self._puente
        if p is not None:
            while not p.solicitudes.empty():
                self._atender(p.solicitudes.get_nowait())
            while not p.eventos.empty():
                self._evento(p.eventos.get_nowait())
        self.after(100, self._bombear)

    def _atender(self, s):
        if s.tipo == "confirmar":
            texto = f"Periodo: {self._periodo}\n\n{s.texto}\n\nContinuar?"
            s.responder(bool(messagebox.askyesno("Zero - confirmacion", texto, icon="warning", default="no", parent=self)))
        else:
            s.responder(simpledialog.askstring("Zero", s.texto or "Contrasena", show="*", parent=self))

    def _evento(self, ev):
        self._avance.registrar(ev)
        if ev[0] == "fin":
            self._terminar(ev[1])
            return
        if ev[0] == "salida":
            self._escribir(ev[1])
        else:
            _, nivel, texto = ev
            etiqueta = "err" if nivel in ("ERROR", "CRITICAL") else "warn" if nivel == "WARNING" else None
            if etiqueta is None and any(f"-> {e}" in texto for e in ("declarado", "simulado", "parcial")):
                etiqueta = "ok"
            self._escribir(texto, etiqueta)
        a = self._avance
        if a.total and self.barra.cget("mode") == "indeterminate":
            self.barra.stop()
            self.barra.config(mode="determinate")
        if a.total:
            self.barra.config(maximum=a.total, value=min(a.hechos, a.total))
            self.estado.config(text=f"Fideicomiso {min(a.hechos + 1, a.total)} de {a.total}")
        self.conteo.config(text=f"{a.correctas} correctas  |  {a.omitidas} ya declaradas u omitidas  |  {a.problemas} con problema")

    def _terminar(self, codigo):
        self._corriendo = False
        self.barra.stop()
        self.barra.config(mode="determinate", maximum=1, value=1 if codigo == 0 else 0)
        self.estado.config(text=FIN.get(codigo, f"Termino con codigo {codigo}"))
        self.clave.delete(0, "end")  # la contrasena no se queda en la ventana
        self._botones(True)
        self._escribir(FIN.get(codigo, f"Termino con codigo {codigo}"), "ok" if codigo == 0 else "warn")
        self._puente = None
        self._actualizar_resumen()

    def _escribir(self, texto, etiqueta=None):
        self.registro.config(state="normal")
        self.registro.insert("end", time.strftime("%H:%M:%S ") , "hora")
        self.registro.insert("end", texto + "\n", etiqueta or ())
        self.registro.see("end")
        self.registro.config(state="disabled")

    def destroy(self):
        for ident in self.tk.splitlist(self.tk.call("after", "info")):  # sin esto quedan 'after' huerfanos y ruido en stderr
            try:
                self.tk.call("after", "cancel", ident)
            except tk.TclError:
                pass
        super().destroy()

    def _cerrar(self):
        if self._corriendo:
            messagebox.showinfo("Zero", "Hay una ejecucion en curso. Pulse Detener y espere a que termine "
                                        "antes de cerrar: asi no queda una declaracion a medias.", parent=self)
            return
        self.destroy()
