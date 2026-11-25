"""
Pantalla de carga en negro y blanco que acompaña al robot mientras trabaja, y el resumen
que aparece si el programa se cae (cuántos RUCs se extrajeron y el tiempo de trabajo).

Tkinter corre en un hilo propio: el hilo principal sigue con Selenium y solo deja el estado
en un dict (con lock) que la ventana lee cada TICK_MS. Todos los objetos de Tk se crean, usan
y liberan dentro de ese hilo, porque Tk no tolera que se los toque desde otro hilo.

Uso desde el hilo principal::

    pantalla = PantallaCarga().iniciar()
    pantalla.actualizar(fase="Procesando RUCs", hechos=10, total=100)
    pantalla.terminar()      # o pantalla.mostrar_resumen(...) si algo falló
    pantalla.cerrar()
"""
import _thread
import ctypes
import logging
import math
import re
import threading
import time
import tkinter as tk

from siac_scraper.ui.formato import cortar as _cortar
from siac_scraper.ui.formato import formato_miles, formato_tiempo

NEGRO, BLANCO, GRIS, GRIS_OSCURO = "#000000", "#ffffff", "#9a9a9a", "#333333"
FUENTE, FUENTE_MONO = "Segoe UI", "Consolas"
ANCHO, ALTO = 520, 314
LADO = 10                     # lado de los cuadros del tablero inferior
TICK_MS = 50                  # cada cuánto se repinta la animación


class PantallaCarga:
    """Ventana pequeña, sin bordes y siempre encima (esquina inferior derecha) que no le quita
    el foco al navegador. Antes de iniciar() se puede llamar a actualizar() sin problema."""

    def __init__(self, titulo="ROBOTO · SIAC ÚNICO"):
        """Prepara el estado; la ventana recién aparece con ``iniciar()``."""
        self.titulo = titulo
        self.inicio = time.time()
        self._estado = {"fase": "Iniciando...", "detalle": "", "log": "",
                        "hechos": 0, "total": 0, "contadores": {}}
        self._lock = threading.Lock()         # protege _estado entre los dos hilos
        self._listo = threading.Event()       # la ventana ya se construyó (o falló)
        self._cerrar = threading.Event()      # el hilo principal pidió cerrar la ventana
        self._resumen = None          # lo pide el hilo principal; lo dibuja el hilo de la ventana
        self._resumen_visto = False
        self._hilo = None
        self._w = {}                  # root, canvas e ítems: solo los toca el hilo de la ventana
        self._frame = 0               # cuadro de animación actual
        self._agarre = (0, 0)         # dónde se agarró la ventana para arrastrarla
        self._t_lote = None           # cuándo empezó a procesar RUCs (base de la velocidad)
        self._t_fin = None            # cuándo terminó: congela reloj y velocidad
        self._deteniendo = False      # ya se pidió detener con la X

    # ------------------- API para el hilo principal -------------------
    def iniciar(self, inicio=None):
        """Abre la ventana en su propio hilo y espera (hasta 5 s) a que esté construida.

        Parámetros:
            inicio: ``time.time()`` desde el que cuenta el reloj; por defecto, ahora.

        Devuelve:
            La misma pantalla, para poder encadenar ``PantallaCarga().iniciar()``.
        """
        self.inicio = inicio or time.time()
        # daemon: si el programa termina, el hilo de la ventana no lo mantiene vivo
        self._hilo = threading.Thread(target=self._correr, name="pantalla_carga", daemon=True)
        self._hilo.start()
        self._listo.wait(5)
        return self

    def activa(self):
        """True si la ventana está abierta (su hilo sigue corriendo)."""
        return self._hilo is not None and self._hilo.is_alive()

    def actualizar(self, **cambios):
        """Cambia lo que muestra la ventana; se ve en el siguiente repintado.

        Claves aceptadas: ``fase``, ``detalle``, ``log``, ``hechos``, ``total`` y
        ``contadores`` (``{etiqueta: número}``). La primera vez que llega ``total`` empieza
        a medirse la velocidad.
        """
        with self._lock:
            self._estado.update(cambios)
            if cambios.get("total") and self._t_lote is None:
                self._t_lote = time.time()

    def terminar(self, fase="Proceso terminado", detalle="Cierra esta ventana con la X para salir"):
        """Deja la pantalla con el resultado final y BLOQUEA hasta que la persona la cierra."""
        if not self.activa():
            return
        self._t_fin = time.time()
        self.actualizar(fase=fase, detalle=detalle, terminado=True)
        while self._hilo.is_alive():
            self._hilo.join(0.5)                  # en pasos cortos: Ctrl+C sigue funcionando

    def cerrar(self):
        """Cierra la ventana (si sigue abierta) y espera hasta 5 s a que termine su hilo."""
        self._cerrar.set()
        if self._hilo is not None:
            self._hilo.join(5)

    def mostrar_resumen(self, titulo, destacados, filas, nota=""):
        """Cambia la pantalla de carga por un resumen y BLOQUEA hasta que la persona lo acepta.

        Parámetros:
            titulo: título del resumen.
            destacados: ``[(valor, etiqueta), ...]`` que se muestran en recuadros grandes.
            filas: ``[(etiqueta, valor), ...]`` que se muestran como tabla.
            nota: texto al pie (ej. el motivo del error).

        Si la ventana no está disponible (no se inició o falló al dibujar), muestra un
        MessageBox de Windows con el mismo contenido.
        """
        if self.activa():
            self._resumen = (titulo, destacados, filas, nota)
            self._hilo.join()                     # termina cuando se presiona Aceptar
        if not self._resumen_visto:
            texto = "\n".join([f"{e}: {v}" for v, e in destacados] + [""] +
                              [f"{e}: {v}" for e, v in filas] + (["", nota] if nota else []))
            ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x10 | 0x40000)  # error + topmost

    # ---------------------- hilo de la ventana ----------------------
    def _correr(self):
        """Cuerpo del hilo de la ventana: crea Tk, construye la ventana y corre su bucle."""
        try:
            root = tk.Tk()
        except Exception:
            self._listo.set()                     # sin pantalla (ej. Tk no instalado): sigue sin ella
            return
        self._w["root"] = root
        try:
            self._construir(root)
            root.after(TICK_MS, self._tick)
            self._listo.set()
            root.mainloop()
        except Exception:
            try:
                root.destroy()
            except Exception:
                pass
        finally:
            self._listo.set()
            self._w.clear()                       # que Tk se libere en este mismo hilo
            del root

    def _construir(self, root):
        """Dibuja la ventana: cabecera, botón X, spinner, barra de progreso, textos y tablero."""
        root.overrideredirect(True)               # sin la barra de título blanca de Windows
        root.attributes("-topmost", True)
        root.configure(bg=NEGRO)
        x = root.winfo_screenwidth() - ANCHO - 24
        y = root.winfo_screenheight() - ALTO - 72   # encima de la barra de tareas
        root.geometry(f"{ANCHO}x{ALTO}+{x}+{y}")

        c = tk.Canvas(root, width=ANCHO, height=ALTO, bg=NEGRO, highlightthickness=0)
        c.pack()
        c.bind("<ButtonPress-1>", self._agarrar)  # se mueve arrastrándola
        c.bind("<B1-Motion>", self._arrastrar)
        self._w["c"] = c

        # cabecera blanca con texto negro
        c.create_rectangle(0, 0, ANCHO, 52, fill=BLANCO, width=0)
        c.create_text(22, 26, text=self.titulo, anchor="w", fill=NEGRO, font=(FUENTE, 13, "bold"))
        self._w["reloj"] = c.create_text(ANCHO - 56, 26, anchor="e", fill=NEGRO,
                                         font=(FUENTE_MONO, 13, "bold"))

        # botón X: detiene todo el proceso (o sale, si ya terminó)
        x0, y0, x1, y1 = ANCHO - 44, 10, ANCHO - 12, 42
        caja_x = c.create_rectangle(x0, y0, x1, y1, fill=BLANCO, outline=NEGRO, width=2, tags="cerrar")
        letra_x = c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="✕", fill=NEGRO,
                                font=(FUENTE, 12, "bold"), tags="cerrar")

        def resaltar_x(activo):
            """Invierte los colores de la X mientras el mouse está encima."""
            c.itemconfigure(caja_x, fill=NEGRO if activo else BLANCO)
            c.itemconfigure(letra_x, fill=BLANCO if activo else NEGRO)

        c.tag_bind("cerrar", "<Enter>", lambda _: resaltar_x(True))
        c.tag_bind("cerrar", "<Leave>", lambda _: resaltar_x(False))
        c.tag_bind("cerrar", "<ButtonRelease-1>", lambda _: self._clic_cerrar())

        # spinner + fase actual
        cx, cy, r = 50, 100, 17
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=GRIS_OSCURO, width=4)
        self._w["giro"] = c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=90,
                                       style="arc", outline=BLANCO, width=4)
        self._w["fase"] = c.create_text(86, 90, anchor="w", fill=BLANCO, font=(FUENTE, 13, "bold"))
        self._w["detalle"] = c.create_text(86, 113, anchor="w", fill=GRIS, font=(FUENTE, 10))

        # barra de progreso: borde blanco, relleno blanco
        self._w["barra"] = (22, 140, ANCHO - 22, 160)
        x0, y0, x1, y1 = self._w["barra"]
        c.create_rectangle(x0, y0, x1, y1, outline=BLANCO, width=2)
        self._w["relleno"] = c.create_rectangle(x0 + 4, y0 + 4, x0 + 4, y1 - 3, fill=BLANCO, width=0)
        self._w["avance"] = c.create_text(x0, 178, anchor="w", fill=BLANCO, font=(FUENTE_MONO, 10))
        self._w["pct"] = c.create_text(x1, 178, anchor="e", fill=BLANCO, font=(FUENTE_MONO, 10, "bold"))
        self._w["ritmo"] = c.create_text(22, 206, anchor="w", fill=BLANCO, font=(FUENTE_MONO, 10, "bold"))
        self._w["conteo"] = c.create_text(22, 230, anchor="w", fill=BLANCO, font=(FUENTE_MONO, 10))
        self._w["log"] = c.create_text(22, 256, anchor="w", fill=GRIS, font=(FUENTE_MONO, 9))

        # tablero inferior: dos filas de cuadros que se desplazan en sentidos opuestos
        cuadros = []
        for fila in range(2):
            for k in range(ANCHO // (2 * LADO) + 2):
                cuadros.append((c.create_rectangle(0, 0, 0, 0, fill=BLANCO, width=0), fila, k))
        self._w["cuadros"] = cuadros
        c.create_rectangle(1, 1, ANCHO - 1, ALTO - 1, outline=BLANCO, width=2)   # borde

    def _tick(self):
        """Se ejecuta cada TICK_MS en el hilo de la ventana: atiende los pedidos del hilo
        principal (cerrar, mostrar el resumen) o repinta la animación, y se reprograma."""
        root = self._w.get("root")
        if root is None:
            return
        if self._cerrar.is_set():
            root.destroy()
            return
        if self._resumen is not None:
            if not self._resumen_visto:
                try:
                    self._dibujar_resumen(*self._resumen)
                    self._resumen_visto = True
                except Exception:
                    root.destroy()                # mostrar_resumen() cae al MessageBox
                    return
        else:
            try:
                self._animar()
            except tk.TclError:
                pass                              # un cuadro perdido no detiene la ventana
        root.after(TICK_MS, self._tick)

    def _animar(self):
        """Repinta un cuadro: reloj, spinner, textos, barra de progreso, velocidad y tablero."""
        c, w = self._w["c"], self._w
        self._frame += 1
        f = self._frame
        with self._lock:
            e = dict(self._estado)                # copia: no retener el lock mientras se dibuja

        ahora = self._t_fin or time.time()
        c.itemconfigure(w["reloj"], text=formato_tiempo(ahora - self.inicio))
        # el arco gira y además se estira y encoge (seno) para que se note el movimiento
        c.itemconfigure(w["giro"], start=(90 - f * 9) % 360, extent=40 + 110 * (1 + math.sin(f / 8)))
        c.itemconfigure(w["fase"], text=_cortar(e["fase"], 40))
        c.itemconfigure(w["detalle"], text=_cortar(e["detalle"], 58))

        x0, y0, x1, y1 = w["barra"]
        util = x1 - x0 - 7                        # ancho interior de la barra (sin el borde)
        hechos, total = e["hechos"], e["total"]
        if total:
            frac = min(1.0, hechos / total)
            c.coords(w["relleno"], x0 + 4, y0 + 4, x0 + 4 + util * frac, y1 - 3)
            c.itemconfigure(w["avance"], text=f"{formato_miles(hechos)} / {formato_miles(total)} RUCs")
            c.itemconfigure(w["pct"], text=f"{100 * frac:.1f} %")
        else:                                     # sin total todavía: un bloque que va y viene
            bloque = util * 0.25
            pos = (1 + math.sin(f / 10)) / 2 * (util - bloque)
            c.coords(w["relleno"], x0 + 4 + pos, y0 + 4, x0 + 4 + pos + bloque, y1 - 3)
            c.itemconfigure(w["avance"], text="preparando...")
            c.itemconfigure(w["pct"], text="")

        # avanzados = RUCs guardados en esta ejecución; velocidad desde que empezó el lote
        avanzados = sum(e["contadores"].values())
        horas = (ahora - self._t_lote) / 3600 if self._t_lote else 0
        velocidad = f"{formato_miles(round(avanzados / horas))} RUCs/h" if avanzados and horas else "—"
        c.itemconfigure(w["ritmo"], text=f"VELOCIDAD {velocidad}   AVANZADOS {formato_miles(avanzados)}")

        conteo = "   ".join(f"{k.upper()} {formato_miles(v)}" for k, v in e["contadores"].items())
        c.itemconfigure(w["conteo"], text=conteo)
        c.itemconfigure(w["log"], text=_cortar(e["log"], 78))

        # tablero: la fila de arriba avanza a la izquierda y la de abajo a la derecha,
        # desfasadas medio paso para formar un damero
        paso = 2 * LADO
        off = f % paso
        y_base = ALTO - 3 - 2 * LADO
        for item, fila, k in w["cuadros"]:
            x = k * paso - off if fila == 0 else (k - 1) * paso + LADO + off
            y = y_base + fila * LADO
            c.coords(item, x, y, x + LADO, y + LADO)

    def _dibujar_resumen(self, titulo, destacados, filas, nota):
        """Reemplaza la pantalla de carga por el resumen, centrado en la pantalla y con un
        botón ACEPTAR (también Enter o Escape) que cierra la ventana."""
        root, c = self._w["root"], self._w["c"]
        c.delete("all")
        W = ANCHO

        c.create_rectangle(0, 0, W, 52, fill=BLANCO, width=0)
        c.create_text(22, 26, text=titulo.upper(), anchor="w", fill=NEGRO, font=(FUENTE, 13, "bold"))
        c.create_text(W - 22, 26, text=time.strftime("%H:%M:%S"), anchor="e", fill=NEGRO,
                      font=(FUENTE_MONO, 12, "bold"))

        # recuadros grandes, alternando negro sobre blanco y blanco sobre negro
        y, sep = 72, 12
        ancho_caja = (W - 44 - sep * (len(destacados) - 1)) / max(1, len(destacados))
        for i, (valor, etiqueta) in enumerate(destacados):
            bx = 22 + i * (ancho_caja + sep)
            fondo, tinta = (BLANCO, NEGRO) if i % 2 else (NEGRO, BLANCO)
            c.create_rectangle(bx, y, bx + ancho_caja, y + 84, fill=fondo, outline=BLANCO, width=2)
            c.create_text(bx + ancho_caja / 2, y + 36, text=valor, fill=tinta, font=(FUENTE_MONO, 24, "bold"))
            c.create_text(bx + ancho_caja / 2, y + 67, text=etiqueta.upper(), fill=tinta, font=(FUENTE, 9, "bold"))
        y += 84 + 24

        # tabla etiqueta / valor
        for etiqueta, valor in filas:
            c.create_text(22, y, text=etiqueta, anchor="w", fill=GRIS, font=(FUENTE, 10))
            c.create_text(W - 22, y, text=valor, anchor="e", fill=BLANCO, font=(FUENTE_MONO, 10, "bold"))
            c.create_line(22, y + 12, W - 22, y + 12, fill=GRIS_OSCURO)
            y += 25

        if nota:
            # la nota puede ocupar varias líneas: se mide su alto real para seguir debajo
            t = c.create_text(22, y + 4, text=nota, anchor="nw", fill=GRIS, font=(FUENTE_MONO, 9), width=W - 44)
            y = c.bbox(t)[3] + 18
        else:
            y += 8

        bw, bh = 150, 36
        bx = (W - bw) / 2
        caja = c.create_rectangle(bx, y, bx + bw, y + bh, fill=BLANCO, outline=BLANCO, width=2, tags="boton")
        texto = c.create_text(W / 2, y + bh / 2, text="ACEPTAR", fill=NEGRO, font=(FUENTE, 10, "bold"), tags="boton")

        def resaltar(activo):
            """Invierte los colores del botón ACEPTAR mientras el mouse está encima."""
            c.itemconfigure(caja, fill=NEGRO if activo else BLANCO)
            c.itemconfigure(texto, fill=BLANCO if activo else NEGRO)

        c.tag_bind("boton", "<Enter>", lambda _: resaltar(True))
        c.tag_bind("boton", "<Leave>", lambda _: resaltar(False))
        c.tag_bind("boton", "<ButtonRelease-1>", lambda _: root.destroy())
        root.bind("<Return>", lambda _: root.destroy())
        root.bind("<Escape>", lambda _: root.destroy())

        # la ventana crece hasta el alto que ocupó el contenido y se centra en la pantalla
        alto = y + bh + 22
        c.create_rectangle(1, 1, W - 1, alto - 1, outline=BLANCO, width=2)
        c.configure(height=alto)
        x = (root.winfo_screenwidth() - W) // 2
        root.geometry(f"{W}x{alto}+{x}+{(root.winfo_screenheight() - alto) // 2}")
        root.lift()
        root.focus_force()
        root.bell()

    def _clic_cerrar(self):
        """X: si ya terminó, cierra la ventana (y el programa sale). Si está trabajando,
        interrumpe el hilo principal como un Ctrl+C: cierra el navegador y termina todo."""
        with self._lock:
            terminado = self._estado.get("terminado")
        if terminado:
            self._w["root"].destroy()
            return
        if self._deteniendo:
            return                                # ya se pidió; un segundo clic no hace nada
        self._deteniendo = True
        self.actualizar(fase="Deteniendo el proceso...", detalle="Cerrando el navegador")
        _thread.interrupt_main()                  # KeyboardInterrupt en el hilo principal

    def _agarrar(self, ev):
        """Recuerda en qué punto de la ventana se hizo clic, para arrastrarla desde ahí."""
        self._agarre = (ev.x, ev.y)

    def _arrastrar(self, ev):
        """Mueve la ventana siguiendo al mouse (no tiene barra de título para arrastrar)."""
        dx, dy = self._agarre
        self._w["root"].geometry(f"+{ev.x_root - dx}+{ev.y_root - dy}")


class HandlerPantalla(logging.Handler):
    """Handler de logging que muestra en la pantalla de carga el último mensaje INFO o superior.

    Quita los prefijos entre corchetes (ej. ``[métricas]``) para que el texto quepa.
    """
    _PREFIJO = re.compile(r"^(\[[^\]]*\]\s*)+")

    def __init__(self, pantalla):
        """``pantalla``: la ``PantallaCarga`` donde se muestran los mensajes."""
        super().__init__(logging.INFO)
        self.pantalla = pantalla

    def emit(self, record):
        """Envía el mensaje a la pantalla. Nunca lanza: un error aquí no debe parar el robot."""
        try:
            self.pantalla.actualizar(log=self._PREFIJO.sub("", record.getMessage()))
        except Exception:
            pass
