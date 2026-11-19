"""Interfaz gráfica de la cámara full espectro: video en vivo, modos espectrales,
autoajuste, reducción de ruido, comparación con el original, sonda de longitud
de onda (clic en la imagen), fotos y video.

Ejecutar:  python interfaz.py   (o doble clic en "Abrir camara.bat")
Atajos:    1-9, 0, e, t modo · a autoajuste · c comparar · espacio foto · g grabar
"""
import ctypes
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2
import numpy as np
from PIL import Image, ImageTk

from detectar_camaras import nombres_dshow
import espectro
from espectro import MODOS, TECLAS, Niveles, Suavizado, describir_color, describir_ir, procesar

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")


def descripcion(indice_modo):
    return " ".join(MODOS[indice_modo][1].__doc__.split())


class Camara(threading.Thread):
    """Lee y procesa cuadros en segundo plano; la interfaz solo los muestra.
    Las acciones sobre el dispositivo llegan por la cola `ordenes` para que se
    ejecuten en este mismo hilo, que es el dueño de la captura DirectShow."""

    def __init__(self, indice, ancho=352, alto=288):
        super().__init__(daemon=True)
        self.indice, self.tamano = indice, (ancho, alto)
        self.niv, self.suav = Niveles(), Suavizado()
        self.modo = 0
        self.ruido = 0.5  # 0 = sin reducción, 0.9 = máxima
        self.comparar = False
        self.ordenes = queue.Queue()
        self.ultimo = None  # (original, procesada, vista)
        self.fps = 0.0
        self.negros = 0
        self.error = None
        self._parar = threading.Event()
        self._grabador = None

    def parar(self):
        self._parar.set()

    def run(self):
        ancho, alto = self.tamano
        cap = cv2.VideoCapture(self.indice, cv2.CAP_DSHOW, [
            cv2.CAP_PROP_FRAME_WIDTH, ancho, cv2.CAP_PROP_FRAME_HEIGHT, alto])
        if not cap.isOpened():
            self.error = "No se pudo abrir la cámara (¿la usa otro programa?, ¿recién conectada?)."
            return
        self.tamano = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        t_prev = time.time()
        try:
            while not self._parar.is_set():
                self._atender_ordenes(cap)
                ok, frame = cap.read()
                if not ok:
                    self.error = "La cámara dejó de enviar imagen (¿se desconectó?)."
                    break
                ahora = time.time()
                self.fps = 0.9 * self.fps + 0.1 / max(ahora - t_prev, 1e-6)
                t_prev = ahora
                # El sensor colgado da media ~0.0; un cuarto muy oscuro aún da 1-15
                self.negros = self.negros + 1 if frame.mean() < 0.3 else 0

                self.suav.peso = 1.0 - self.ruido
                procesada = procesar(frame, self.modo, self.niv,
                                     self.suav if self.ruido > 0 else None)
                if self._grabador is not None:
                    self._grabador.write(procesada)
                vista = np.hstack([frame, procesada]) if self.comparar else procesada
                self.ultimo = (frame, procesada, vista)
        finally:
            self._cerrar_grabacion()
            cap.release()

    def _atender_ordenes(self, cap):
        while True:
            try:
                orden, *args = self.ordenes.get_nowait()
            except queue.Empty:
                return
            if orden == "driver":
                cap.set(cv2.CAP_PROP_SETTINGS, 1)  # panel de propiedades del driver
            elif orden == "grabar":
                fps = min(30.0, max(5.0, round(self.fps)))
                self._grabador = cv2.VideoWriter(args[0], cv2.VideoWriter_fourcc(*"MJPG"),
                                                 fps, self.tamano)
            elif orden == "parar_grabacion":
                self._cerrar_grabacion()

    def _cerrar_grabacion(self):
        if self._grabador is not None:
            self._grabador.release()
            self._grabador = None


class App:
    def __init__(self, raiz):
        self.raiz = raiz
        self.cam = None
        self.grabando = False
        self.mostrado = None
        self.imagen_tk = None
        self.geometria = None  # (x0, y0, escala) de la imagen dentro del lienzo
        self.sonda = None      # (texto, hora) del último clic en la imagen

        raiz.title("Cámara full espectro")
        raiz.geometry("1240x760")
        raiz.minsize(900, 640)
        raiz.protocol("WM_DELETE_WINDOW", self.salir)

        self.var_modo = tk.IntVar(value=0)
        self.var_auto = tk.BooleanVar(value=True)
        self.var_ruido = tk.DoubleVar(value=50)
        self.var_comparar = tk.BooleanVar(value=False)
        self.var_filtro = tk.BooleanVar(value=False)
        self.var_camara = tk.StringVar()
        self.var_estado = tk.StringVar(value="Buscando cámaras...")

        self._construir()
        raiz.bind("<Key>", self._tecla)
        raiz.after(100, self.refrescar_camaras, True)
        raiz.after(30, self._actualizar)

    # --- construcción de la ventana ---

    def _construir(self):
        self.raiz.columnconfigure(0, weight=1)
        self.raiz.rowconfigure(0, weight=1)

        self.lienzo = tk.Canvas(self.raiz, bg="#111", highlightthickness=0, cursor="crosshair")
        self.lienzo.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self.item_imagen = self.lienzo.create_image(0, 0, anchor="center")
        self.item_texto = self.lienzo.create_text(0, 0, fill="#888", font=("Segoe UI", 12),
                                                  text="Sin cámara conectada")
        self.item_sonda = self.lienzo.create_oval(0, 0, 0, 0, outline="#0f0", width=2, state="hidden")
        self.lienzo.bind("<Button-1>", self._sondear)

        panel = ttk.Frame(self.raiz, width=340)
        panel.grid(row=0, column=1, sticky="ns", padx=(4, 8), pady=8)

        caja = ttk.LabelFrame(panel, text="Cámara", padding=8)
        caja.pack(fill="x")
        fila = ttk.Frame(caja)
        fila.pack(fill="x")
        self.combo = ttk.Combobox(fila, textvariable=self.var_camara, state="readonly", width=26)
        self.combo.pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="↻", width=3, command=self.refrescar_camaras).pack(side="left", padx=(4, 0))
        self.boton_conectar = ttk.Button(caja, text="Conectar", command=self.conectar)
        self.boton_conectar.pack(fill="x", pady=(6, 0))

        caja = ttk.LabelFrame(panel, text="Modo espectral", padding=8)
        caja.pack(fill="x", pady=(8, 0))
        rejilla = ttk.Frame(caja)
        rejilla.pack(fill="x")
        filas = (len(MODOS) + 1) // 2
        for i, (nombre, _) in enumerate(MODOS):
            ttk.Radiobutton(rejilla, text=f"{TECLAS[i]}  {nombre}", value=i, variable=self.var_modo,
                            command=self._aplicar).grid(row=i % filas, column=i // filas, sticky="w",
                                                        padx=(0, 8))
        self.lbl_desc = ttk.Label(caja, wraplength=310, foreground="#555", justify="left")
        self.lbl_desc.pack(fill="x", pady=(6, 0))

        caja = ttk.LabelFrame(panel, text="Ajustes", padding=8)
        caja.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(caja, text="Autoajuste de brillo  (a)", variable=self.var_auto,
                        command=self._aplicar).pack(anchor="w")
        ttk.Checkbutton(caja, text="Comparar con el original  (c)", variable=self.var_comparar,
                        command=self._aplicar).pack(anchor="w")
        ttk.Checkbutton(caja, text="Tengo un filtro IR 720 nm puesto", variable=self.var_filtro,
                        command=self._aplicar).pack(anchor="w")
        self.lbl_ruido = ttk.Label(caja)
        self.lbl_ruido.pack(anchor="w", pady=(6, 0))
        ttk.Scale(caja, from_=0, to=90, variable=self.var_ruido,
                  command=lambda _: self._aplicar()).pack(fill="x")
        ttk.Button(caja, text="Exposición y color del driver…",
                   command=lambda: self._orden("driver")).pack(fill="x", pady=(8, 0))

        caja = ttk.LabelFrame(panel, text="Capturar", padding=8)
        caja.pack(fill="x", pady=(8, 0))
        fila = ttk.Frame(caja)
        fila.pack(fill="x")
        ttk.Button(fila, text="Foto  (espacio)", command=self.foto).pack(side="left", fill="x", expand=True)
        self.boton_grabar = ttk.Button(fila, text="Grabar  (g)", command=self.grabar)
        self.boton_grabar.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(caja, text="Abrir carpeta de capturas", command=self.abrir_carpeta).pack(fill="x", pady=(6, 0))

        ttk.Label(self.raiz, textvariable=self.var_estado, anchor="w", padding=(10, 2)).grid(
            row=1, column=0, columnspan=2, sticky="ew")
        self._aplicar()

    # --- cámara ---

    def refrescar_camaras(self, conectar_dlink=False):
        nombres = nombres_dshow() or [f"Cámara {i}" for i in range(4)]
        self.combo["values"] = nombres
        dlink = next((i for i, n in enumerate(nombres) if "DSB-C120" in n), None)
        self.combo.current(dlink if dlink is not None else 0)
        self.var_estado.set(f"{len(nombres)} cámara(s) encontradas.")
        if conectar_dlink and dlink is not None and self.cam is None:
            self.conectar()

    def conectar(self):
        if self.cam is not None:
            self.desconectar()
            return
        indice = self.combo.current()
        if indice < 0:
            return
        self.cam = Camara(indice)
        self._aplicar()
        self.cam.start()
        self.boton_conectar.config(text="Desconectar")
        self.var_estado.set(f"Conectando a {self.var_camara.get()}...")

    def desconectar(self, mensaje="Desconectada."):
        if self.grabando:
            self.grabar()
        if self.cam is not None:
            self.cam.parar()
            self.cam.join(timeout=2)
            self.cam = None
        self.mostrado = None
        self.lienzo.itemconfig(self.item_imagen, image="")
        self.lienzo.itemconfig(self.item_texto, text="Sin cámara conectada")
        self.boton_conectar.config(text="Conectar")
        self.var_estado.set(mensaje)

    def _orden(self, *orden):
        if self.cam is not None:
            self.cam.ordenes.put(orden)

    def _aplicar(self):
        """Pasa los controles de la interfaz a la cámara."""
        modo = self.var_modo.get()
        self.lbl_desc.config(text=descripcion(modo))
        self.lbl_ruido.config(text=f"Reducción de ruido: {self.var_ruido.get():.0f} %")
        espectro.CONFIG["filtro_ir"] = self.var_filtro.get()
        if self.cam is not None:
            self.cam.modo = modo
            self.cam.niv.activo = self.var_auto.get()
            self.cam.ruido = self.var_ruido.get() / 100
            self.cam.comparar = self.var_comparar.get()

    # --- capturas ---

    def foto(self):
        if self.cam is None or self.cam.ultimo is None:
            return
        original, procesada, _ = self.cam.ultimo
        os.makedirs(CARPETA, exist_ok=True)
        base = os.path.join(CARPETA, datetime.now().strftime("foto_%Y%m%d_%H%M%S"))
        cv2.imwrite(base + "_original.png", original)
        cv2.imwrite(base + f"_modo{self.var_modo.get() + 1}.png", procesada)
        self.var_estado.set(f"Foto guardada: {os.path.basename(base)}_*.png")

    def grabar(self):
        if self.cam is None:
            return
        if self.grabando:
            self._orden("parar_grabacion")
            self.grabando = False
            self.boton_grabar.config(text="Grabar  (g)")
        else:
            os.makedirs(CARPETA, exist_ok=True)
            ruta = os.path.join(CARPETA, datetime.now().strftime("video_%Y%m%d_%H%M%S.avi"))
            self._orden("grabar", ruta)
            self.grabando = True
            self.boton_grabar.config(text="■ Detener")

    def abrir_carpeta(self):
        os.makedirs(CARPETA, exist_ok=True)
        os.startfile(CARPETA)

    # --- bucle de la interfaz ---

    def _actualizar(self):
        cam = self.cam
        if cam is not None:
            if cam.error:
                self.desconectar(cam.error)
            elif cam.ultimo is not None and cam.ultimo is not self.mostrado:
                self.mostrado = cam.ultimo
                self._mostrar(cam.ultimo[2])
                estado = f"{self.var_camara.get()} · {cam.tamano[0]}x{cam.tamano[1]} · {cam.fps:4.1f} fps"
                if cam.negros > 15:
                    estado += " · ⚠ Imagen negra: ¿lente tapado? Si hay luz, reconecta la cámara"
                if self.grabando:
                    estado += " · ● GRABANDO"
                if self.sonda and time.time() - self.sonda[1] < 8:
                    estado += " · " + self.sonda[0]
                else:
                    self.lienzo.itemconfig(self.item_sonda, state="hidden")
                self.var_estado.set(estado)
        self.raiz.after(15, self._actualizar)

    def _mostrar(self, img):
        w, h = self.lienzo.winfo_width(), self.lienzo.winfo_height()
        ih, iw = img.shape[:2]
        escala = min(w / iw, h / ih)
        if escala <= 0:
            return
        nw, nh = max(1, int(iw * escala)), max(1, int(ih * escala))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        self.imagen_tk = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        self.lienzo.itemconfig(self.item_imagen, image=self.imagen_tk)
        self.lienzo.coords(self.item_imagen, w // 2, h // 2)
        self.lienzo.itemconfig(self.item_texto, text="")
        self.geometria = (w // 2 - nw // 2, h // 2 - nh // 2, escala)

    def _sondear(self, evento):
        """Clic en la imagen: longitud de onda aproximada del punto (visible e IR)."""
        if self.cam is None or self.cam.ultimo is None or self.geometria is None:
            return
        original, _, vista = self.cam.ultimo
        x0, y0, escala = self.geometria
        x, y = int((evento.x - x0) / escala), int((evento.y - y0) / escala)
        alto, ancho = original.shape[:2]
        if not (0 <= y < alto and 0 <= x < vista.shape[1]):
            return
        x %= ancho  # en modo comparar, las dos mitades son el mismo punto de la escena
        zona = original[max(0, y - 2):y + 3, max(0, x - 2):x + 3].reshape(-1, 3).mean(axis=0) / 255
        self.sonda = (f"Punto ({x},{y}): visible {describir_color(zona)} | {describir_ir(zona)}",
                      time.time())
        self.lienzo.coords(self.item_sonda, evento.x - 7, evento.y - 7, evento.x + 7, evento.y + 7)
        self.lienzo.itemconfig(self.item_sonda, state="normal")

    def _tecla(self, evento):
        c = evento.char
        if c and c in TECLAS[:len(MODOS)]:
            self.var_modo.set(TECLAS.index(c))
        elif c == "a":
            self.var_auto.set(not self.var_auto.get())
        elif c == "c":
            self.var_comparar.set(not self.var_comparar.get())
        elif c == " ":
            self.foto()
            return
        elif c == "g":
            self.grabar()
            return
        else:
            return
        self._aplicar()

    def salir(self):
        self.desconectar()
        self.raiz.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texto nítido en pantallas con escalado
    except (AttributeError, OSError):
        pass
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
