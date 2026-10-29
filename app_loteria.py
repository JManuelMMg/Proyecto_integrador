"""Aplicación didáctica de escritorio para la lotería mazahua."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from uuid import uuid4

from ffpyplayer.player import MediaPlayer
from PIL import Image, ImageOps, ImageTk

from base_datos import (EXTENSIONES, IDIOMAS, RUTA_BD, asignar_uid, cargar_medio, conectar, crear_carta, eliminar_carta, emparejar_lectura,
                        crear_esquema, guardar_textos, importar_archivos, importar_audios_ingles, obtener_carta, obtener_medio,
                        reasignar_uid, resumen)
from catalogo_loteria import clave
from lector_rfid import LectorRFID, comando_grabar, listar_puertos, recortar_16

FUENTE = "Segoe UI"
TEMAS = {
    "claro": {
        "fondo": "#EEF3FB", "superficie": "#FFFFFF", "panel": "#F6F8FC", "texto": "#16213A", "suave": "#71809A",
        "borde": "#DCE4F0", "lienzo": "#F8FAFE", "header": "#162B52", "header_suave": "#B9CAE8",
        "header_boton": "#254472", "header_activo": "#31598E", "acento": "#5661E9", "acento_activo": "#414CCB",
        "seleccion": "#E9E5FF", "seleccion_texto": "#2B1F6B", "progreso": "#12927A",
        "es_fondo": "#FFF1E8", "mz_fondo": "#E6F8F1", "en_fondo": "#EAF2FF",
    },
    "oscuro": {
        "fondo": "#101827", "superficie": "#182235", "panel": "#202D43", "texto": "#F2F6FC", "suave": "#9EACC1",
        "borde": "#2C3C56", "lienzo": "#121D2E", "header": "#0B1730", "header_suave": "#AFC4E6",
        "header_boton": "#1D3A66", "header_activo": "#295184", "acento": "#8490FF", "acento_activo": "#A4ADFF",
        "seleccion": "#3B3277", "seleccion_texto": "#FFFFFF", "progreso": "#34C9A5",
        "es_fondo": "#3A2A24", "mz_fondo": "#193C39", "en_fondo": "#1D3152",
    },
}
ORDEN_JUEGO = ("mazahua", "español", "inglés")  # orden en que suenan los audios en el modo Juego
# Idioma -> (nombre visible, color, color al pasar el ratón, tecla de atajo)
IDIOMA_UI = {
    "español": ("Español", "#E8702A", "#C95A18", "1"),
    "mazahua": ("Mazahua", "#12927A", "#0B7360", "2"),
    "inglés": ("English", "#2F6FDB", "#1F56B5", "3"),
}
ATAJOS = {"1": "español", "2": "mazahua", "3": "inglés", "space": "mazahua"}
INSTRUCCIONES = {
    "basica": "Mira la imagen y escucha cómo se dice.  Atajos: 1 Español · 2 Mazahua · 3 English",
    "superior": "Escribe la palabra y carga el audio de cada idioma. La imagen se cambia abajo.",
    "juego": "Acerca una tarjeta al lector: se muestra y suena en mazahua, español e inglés.",
}


class AplicacionLoteria(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Lotería Mazahua · Aprende jugando")
        # Tamaño ajustado a la pantalla (deja sitio a la barra de tareas) y centrado.
        ancho = min(1280, self.winfo_screenwidth() - 60)
        alto = min(800, self.winfo_screenheight() - 110)
        self.geometry(f"{ancho}x{alto}+{(self.winfo_screenwidth() - ancho) // 2}+20")
        self.minsize(980, 620)
        self.conexion = conectar()
        crear_esquema(self.conexion)
        self.lecturas: queue.Queue = queue.Queue()
        self.lector: LectorRFID | None = None
        self.esperando_tarjeta = False  # True: la próxima tarjeta leída se asigna a la carta actual
        self.cola_audio: list[str] = []  # idiomas pendientes de sonar en secuencia
        self.idioma_sonando: str | None = None
        self.grabando_carta: int | None = None  # carta cuyos textos se están grabando en una tarjeta
        self.carta_actual: int | None = None
        self.filas: dict[int, dict] = {}
        self.imagen_tk = None
        self._imagen_pil: Image.Image | None = None
        self._render_pendiente: str | None = None
        self._id_lecturas: str | None = None
        self.reproductor: MediaPlayer | None = None
        self.archivo_audio: Path | None = None
        self.audio_temporal = False
        self.sesion_audio: str | None = None
        self.duracion_audio = 0.0
        self.inicio_audio = 0.0
        self.nivel = tk.StringVar(value="basica")
        self.busqueda = tk.StringVar()
        self.textos = {idioma: tk.StringVar() for idioma in IDIOMAS}
        self.modo_oscuro = False
        self.tema = TEMAS["claro"]
        self._tematicos: list[tuple[tk.Widget, dict[str, str]]] = []
        self._botones: dict[tk.Button, object] = {}
        self._crear_interfaz()
        self.aplicar_tema()
        self.recargar()
        if not self.filas:
            self.importar()
        self.cambiar_nivel()
        self._revisar_lecturas()
        self.bind("<Key>", self._atajo_teclado)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

    # ---------- utilidades de tema ----------
    def _con_tema(self, widget, **tokens):
        """Registra un widget: ``aplicar_tema`` le asigna los colores del tema (o el literal dado)."""
        self._tematicos.append((widget, tokens))
        return widget

    def _tarjeta(self, padre, tema_bg: str = "superficie", **opciones) -> tk.Frame:
        """Superficie con borde fino, base de todos los paneles."""
        return self._con_tema(tk.Frame(padre, highlightthickness=1, bd=0, **opciones),
                       bg=tema_bg, highlightbackground="borde", highlightcolor="borde")

    def _etiqueta(self, padre, texto="", tamano=10, peso="normal", fg="texto", bg="superficie", **opciones) -> tk.Label:
        return self._con_tema(tk.Label(padre, text=texto, font=(FUENTE, tamano, peso), **opciones), bg=bg, fg=fg)

    def _boton(self, padre, texto, comando, estilo: object = "secundario", **opciones) -> tk.Button:
        """``estilo``: "secundario", "acento", "header" o una tupla (color, color_hover)."""
        opciones = {"font": (FUENTE, 10, "bold"), "padx": 14, "pady": 8,
                    "highlightthickness": 0, "takefocus": False, **opciones}
        boton = tk.Button(padre, text=texto, command=comando, relief="flat", bd=0,
                          cursor="hand2", **opciones)
        self._botones[boton] = estilo
        boton.bind("<Enter>", lambda _e: self._pintar_boton(boton, encima=True))
        boton.bind("<Leave>", lambda _e: self._pintar_boton(boton))
        return boton

    def _pintar_boton(self, boton: tk.Button, encima: bool = False) -> None:
        t, estilo = self.tema, self._botones[boton]
        if estilo == "secundario":
            base, activo, fg = t["panel"], t["seleccion"], t["texto"]
        elif estilo == "acento":
            base, activo, fg = t["acento"], t["acento_activo"], "#FFFFFF"
        elif estilo == "header":
            base, activo, fg = t["header_boton"], t["header_activo"], "#FFFFFF"
        else:
            (base, activo), fg = estilo, "#FFFFFF"
        if str(boton["state"]) == "disabled":
            boton.configure(bg=t["borde"], disabledforeground=t["suave"])
        else:
            boton.configure(bg=activo if encima else base, fg=fg, activebackground=activo, activeforeground=fg)

    def _habilitar(self, boton: tk.Button, activo: bool) -> None:
        boton.configure(state="normal" if activo else "disabled")
        self._pintar_boton(boton)

    def alternar_tema(self) -> None:
        self.modo_oscuro = not self.modo_oscuro
        self.aplicar_tema()

    def aplicar_tema(self) -> None:
        t = self.tema = TEMAS["oscuro" if self.modo_oscuro else "claro"]
        self.configure(bg=t["fondo"])
        for widget, tokens in self._tematicos:
            widget.configure(**{opcion: t.get(valor, valor) for opcion, valor in tokens.items()})
        for boton in self._botones:
            self._pintar_boton(boton)
        self.boton_tema.configure(text="☀  Tema claro" if self.modo_oscuro else "☾  Tema oscuro")
        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("Treeview", background=t["superficie"], fieldbackground=t["superficie"], foreground=t["texto"],
                         rowheight=38, font=(FUENTE, 10), borderwidth=0, relief="flat")
        estilo.configure("Treeview.Heading", background=t["panel"], foreground=t["suave"], font=(FUENTE, 9, "bold"),
                         relief="flat", borderwidth=0, padding=(10, 8))
        estilo.map("Treeview", background=[("selected", t["seleccion"])], foreground=[("selected", t["seleccion_texto"])])
        estilo.map("Treeview.Heading", background=[("active", t["borde"])])
        estilo.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # sin marco 3D
        estilo.configure("TEntry", fieldbackground=t["panel"], foreground=t["texto"], insertcolor=t["texto"],
                         bordercolor=t["borde"], lightcolor=t["borde"], darkcolor=t["borde"], padding=(10, 8))
        estilo.map("TEntry", bordercolor=[("focus", t["acento"])], lightcolor=[("focus", t["acento"])])
        estilo.configure("Vertical.TScrollbar", troughcolor=t["superficie"], background=t["borde"], bordercolor=t["superficie"],
                         arrowcolor=t["suave"], lightcolor=t["borde"], darkcolor=t["borde"])
        self.tabla.tag_configure("par", background=t["panel"])
        if hasattr(self, "lienzo_cabecera"):
            self._pintar_cabecera()
        if hasattr(self, "ambiente_imagen"):
            self._dibujar_ambiente_imagen()
        self._dibujar_estadisticas()
        self._dibujar_progreso(0)

    @staticmethod
    def _mezclar_color(inicio: str, final: str, proporcion: float) -> str:
        """Mezcla dos colores hexadecimales para los degradados dibujados en Tk."""
        proporcion = max(0.0, min(1.0, proporcion))
        a = tuple(int(inicio[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(final[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % tuple(round(x + (y - x) * proporcion) for x, y in zip(a, b))

    def _pintar_cabecera(self, _evento=None) -> None:
        """Renderiza un degradado suave y brillos difuminados detrás de la marca."""
        lienzo = self.lienzo_cabecera
        ancho, alto = max(1, lienzo.winfo_width()), max(1, lienzo.winfo_height())
        oscuro = self.modo_oscuro
        inicio, final = (("#101D3A", "#4E54C8") if not oscuro else ("#081226", "#202E68"))
        lienzo.delete("fondo")
        for x in range(ancho):
            color = self._mezclar_color(inicio, final, x / max(1, ancho - 1))
            lienzo.create_line(x, 0, x, alto, fill=color, tags="fondo")
        # Capas con tramado: simulan una luz suave sin depender de imágenes externas.
        brillo_a = "#7BCBFF" if not oscuro else "#5874ED"
        brillo_b = "#C7A4FF" if not oscuro else "#6D47BD"
        lienzo.create_oval(ancho * .58, -alto * .8, ancho * 1.08, alto * 1.5,
                           fill=brillo_a, outline="", stipple="gray25", tags="fondo brillo_a")
        lienzo.create_oval(ancho * .77, -alto * .55, ancho * 1.15, alto * 1.2,
                           fill=brillo_b, outline="", stipple="gray25", tags="fondo brillo_b")
        lienzo.tag_lower("fondo")
        self._acomodar_cabecera()

    def _acomodar_cabecera(self) -> None:
        if not hasattr(self, "lienzo_cabecera"):
            return
        lienzo = self.lienzo_cabecera
        ancho, alto = max(1, lienzo.winfo_width()), max(1, lienzo.winfo_height())
        lienzo.coords(self.ventana_marca, 30, alto / 2)
        lienzo.coords(self.ventana_acciones, ancho - 30, alto / 2)

    def _animar_cabecera(self) -> None:
        """Anima despacio los brillos para que el fondo se sienta vivo, no distractor."""
        if not self.winfo_exists() or not hasattr(self, "lienzo_cabecera"):
            return
        lienzo = self.lienzo_cabecera
        ancho, alto = max(1, lienzo.winfo_width()), max(1, lienzo.winfo_height())
        self._fase_brillo = (self._fase_brillo + 1) % 240
        desplazamiento = (self._fase_brillo - 120) * ancho / 2400
        lienzo.coords("brillo_a", ancho * .58 + desplazamiento, -alto * .8,
                      ancho * 1.08 + desplazamiento, alto * 1.5)
        lienzo.coords("brillo_b", ancho * .77 - desplazamiento, -alto * .55,
                      ancho * 1.15 - desplazamiento, alto * 1.2)
        self.after(70, self._animar_cabecera)

    # ---------- construcción de la interfaz ----------
    def _crear_interfaz(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._crear_encabezado()
        self._crear_barra()
        cuerpo = self._con_tema(tk.Frame(self, padx=26, pady=22), bg="fondo")
        cuerpo.grid(row=2, column=0, sticky="nsew")
        cuerpo.columnconfigure(1, weight=1)
        cuerpo.rowconfigure(0, weight=1)
        self._crear_lateral(cuerpo)
        contenido = self._con_tema(tk.Frame(cuerpo), bg="fondo")
        contenido.grid(row=0, column=1, sticky="nsew")
        contenido.columnconfigure(0, weight=1)
        contenido.rowconfigure(0, weight=1)
        self._crear_visor(contenido)
        self._crear_edicion(contenido)

    def _crear_encabezado(self) -> None:
        self._fase_brillo = 0
        self.lienzo_cabecera = tk.Canvas(self, height=130, highlightthickness=0, bd=0)
        self.lienzo_cabecera.grid(row=0, column=0, sticky="ew")
        self.lienzo_cabecera.bind("<Configure>", self._pintar_cabecera)

        marca = self._con_tema(tk.Frame(self.lienzo_cabecera), bg="header")
        self._etiqueta(marca, "✦", 19, "bold", fg="#82D9FF", bg="header").pack(side="left", padx=(0, 12))
        textos_marca = self._con_tema(tk.Frame(marca), bg="header")
        textos_marca.pack(side="left")
        self._etiqueta(textos_marca, "Lotería Mazahua", 21, "bold", fg="#FFFFFF", bg="header").pack(anchor="w")
        self._etiqueta(textos_marca, "Explora palabras · escucha · aprende", 10, fg="header_suave", bg="header").pack(anchor="w", pady=(2, 0))
        acciones = self._con_tema(tk.Frame(self.lienzo_cabecera), bg="header")
        self.boton_rfid = self._boton(acciones, "◉  Conectar lector", self.alternar_lector, "header")
        self.boton_rfid.pack(side="left", padx=(0, 8))
        self._boton(acciones, "⟳  Importar recursos", self.importar, "header").pack(side="left", padx=(0, 8))
        self._boton(acciones, "🇺🇸  Audios EN", self.importar_audios_ingles, "header").pack(side="left", padx=(0, 8))
        self.boton_tema = self._boton(acciones, "☾", self.alternar_tema, "header", padx=12)
        self.boton_tema.pack(side="left")
        self.ventana_marca = self.lienzo_cabecera.create_window(30, 65, window=marca, anchor="w")
        self.ventana_acciones = self.lienzo_cabecera.create_window(1, 65, window=acciones, anchor="e")
        self._pintar_cabecera()
        self.after(70, self._animar_cabecera)

    def _crear_barra(self) -> None:
        barra = self._con_tema(tk.Frame(self, padx=28, pady=11), bg="superficie")
        barra.grid(row=1, column=0, sticky="ew")
        self._etiqueta(barra, "Modo", 10, "bold", fg="suave").pack(side="left", padx=(0, 10))
        for valor, texto in (("basica", "Primaria"), ("superior", "Media superior · Edición"), ("juego", "▶  Juego · Tarjetas")):
            radio = tk.Radiobutton(barra, text=texto, variable=self.nivel, value=valor, command=self.cambiar_nivel,
                                   indicatoron=False, relief="flat", bd=0, offrelief="flat", cursor="hand2",
                                   font=(FUENTE, 10, "bold"), padx=15, pady=7)
            self._con_tema(radio, bg="panel", fg="texto", selectcolor="seleccion", activebackground="borde", activeforeground="texto")
            radio.pack(side="left", padx=(0, 4))
        self.estado = self._etiqueta(barra, f"Base de datos: {RUTA_BD.name}", 10, fg="suave")
        self.estado.pack(side="right")

    def _crear_lateral(self, padre) -> None:
        lateral = self.lateral = self._tarjeta(padre, width=350, padx=16, pady=17)
        lateral.grid(row=0, column=0, sticky="ns", padx=(0, 20))
        lateral.pack_propagate(False)
        cabecera = self._con_tema(tk.Frame(lateral), bg="superficie")
        cabecera.pack(fill="x")
        self._etiqueta(cabecera, "CATÁLOGO", 9, "bold", fg="acento").pack(anchor="w")
        self._etiqueta(cabecera, "Cartas", 16, "bold").pack(side="left", pady=(3, 0))
        self.contador = self._etiqueta(cabecera, "", 10, fg="suave")
        self.contador.pack(side="right")
        self._boton(lateral, "+  Nueva carta", self.nueva_carta, "acento", pady=9).pack(fill="x", pady=(14, 0))
        ttk.Entry(lateral, textvariable=self.busqueda, font=(FUENTE, 11)).pack(fill="x", pady=(10, 4))
        self._etiqueta(lateral, "Buscar en español, mazahua o inglés", 8, fg="suave").pack(anchor="w")
        self.busqueda.trace_add("write", lambda *_: self._llenar_tabla())
        self.estadisticas = self._con_tema(tk.Canvas(lateral, height=72, highlightthickness=0), bg="superficie")
        self.estadisticas.pack(fill="x", pady=(14, 10))
        self.estadisticas.bind("<Configure>", lambda _e: self._dibujar_estadisticas())
        lista = self._con_tema(tk.Frame(lateral), bg="superficie")
        lista.pack(fill="both", expand=True)
        columnas = ("nombre", "imagen", "es", "mz", "en", "rf")
        self.tabla = ttk.Treeview(lista, columns=columnas, show="headings", selectmode="browse")
        for campo, texto, ancho in (("nombre", "CARTA", 130), ("imagen", "IMG", 42), ("es", "ES", 34),
                                    ("mz", "MZ", 34), ("en", "EN", 34), ("rf", "RFID", 42)):
            self.tabla.heading(campo, text=texto, anchor="w" if campo == "nombre" else "center")
            self.tabla.column(campo, width=ancho, stretch=campo == "nombre", anchor="w" if campo == "nombre" else "center")
        scroll = ttk.Scrollbar(lista, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")  # primero, para que la tabla nunca lo empuje fuera
        self.tabla.pack(side="left", fill="both", expand=True)
        self.tabla.bind("<<TreeviewSelect>>", self.seleccionar)

    def _crear_visor(self, padre) -> None:
        tarjeta = self._tarjeta(padre, padx=28, pady=25)
        tarjeta.grid(row=0, column=0, sticky="nsew")
        # La edición necesita más ancho que la vista previa; así los tres idiomas
        # quedan siempre visibles sin que la imagen monopolice la pantalla.
        tarjeta.columnconfigure(0, weight=4, minsize=230)
        tarjeta.columnconfigure(1, weight=6, minsize=300)
        tarjeta.rowconfigure(1, weight=1)
        cabecera = self._con_tema(tk.Frame(tarjeta), bg="superficie")
        cabecera.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.etiqueta_carta = self._etiqueta(cabecera, "CARTA", 9, "bold", fg="acento")
        self.etiqueta_carta.pack(anchor="w")
        self.titulo = self._etiqueta(cabecera, "Selecciona una carta", 25, "bold", anchor="w")
        self.titulo.pack(fill="x", pady=(3, 0))
        self.instruccion = self._etiqueta(cabecera, INSTRUCCIONES["basica"], 10, fg="suave", anchor="w")
        self.instruccion.pack(fill="x")

        # La imagen se coloca con place() para que nunca agrande el marco: se adapta a él.
        self.marco_imagen = self._con_tema(tk.Frame(tarjeta, highlightthickness=1, bd=0), bg="lienzo",
                                    highlightbackground="borde", highlightcolor="borde")
        self.marco_imagen.grid(row=1, column=0, sticky="nsew", pady=14, padx=(0, 18))
        self._fase_ambiente = 0
        self.ambiente_imagen = self._con_tema(
            tk.Canvas(self.marco_imagen, highlightthickness=0, bd=0), bg="lienzo"
        )
        self.ambiente_imagen.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.ambiente_imagen.bind("<Configure>", lambda _e: self._dibujar_ambiente_imagen())
        self._etiqueta(self.marco_imagen, "VISTA PREVIA", 8, "bold", fg="suave", bg="lienzo").place(x=14, y=12)
        self.imagen = self._etiqueta(self.marco_imagen, "Elige una carta de la lista", 13, fg="suave", bg="lienzo")
        self.imagen.place(relx=0.5, rely=0.5, anchor="center")
        self.marco_imagen.bind("<Configure>", self._redimensionar_previa)
        self.after(90, self._animar_ambiente_imagen)

        idiomas = self._con_tema(tk.Frame(tarjeta), bg="superficie")
        idiomas.grid(row=1, column=1, sticky="nsew", pady=14)
        idiomas.columnconfigure(0, weight=1)
        # Tres filas compactas: en Edición los tres campos (incluido inglés)
        # caben al mismo tiempo, incluso en una pantalla pequeña.
        self.tiles: dict[str, dict[str, tk.Widget]] = {}
        for indice, idioma in enumerate(IDIOMAS):
            idiomas.rowconfigure(indice, weight=1, minsize=76)
            nombre, color, hover, tecla = IDIOMA_UI[idioma]
            tono = {"español": "es_fondo", "mazahua": "mz_fondo", "inglés": "en_fondo"}[idioma]
            tile = self._tarjeta(idiomas, tema_bg=tono)
            tile.grid(row=indice, column=0, sticky="nsew", pady=(0, 7 if indice < len(IDIOMAS) - 1 else 0))
            tile.bind("<Enter>", lambda _e, t=tile: self._resaltar_tile(t, True))
            tile.bind("<Leave>", lambda _e, t=tile: self._resaltar_tile(t, False))
            tk.Frame(tile, bg=color, width=5).pack(side="left", fill="y")
            acciones = self._con_tema(tk.Frame(tile, pady=6), bg=tono)
            acciones.pack(side="right", padx=8)
            boton = self._boton(acciones, "▶", lambda i=idioma: self.reproducir(i), (color, hover), state="disabled", padx=10, pady=6)
            boton.pack(side="left")
            cargar = self._boton(acciones, "Audio…", lambda i=idioma: self.cargar(i), font=(FUENTE, 9, "bold"), padx=8, pady=6)
            texto = self._con_tema(tk.Frame(tile, padx=12, pady=7), bg=tono)
            texto.pack(side="left", fill="both", expand=True)
            self._etiqueta(texto, f"{nombre.upper()}  ·  tecla {tecla}", 8, "bold", fg=color, bg=tono, anchor="w").pack(fill="x")
            palabra = self._etiqueta(texto, "—", 15, "bold", bg=tono, anchor="w", wraplength=180, justify="left")
            palabra.pack(fill="x")
            entrada = ttk.Entry(texto, textvariable=self.textos[idioma], font=(FUENTE, 11), width=12)
            entrada.bind("<Return>", lambda _e: self.guardar_textos())
            self.tiles[idioma] = {"palabra": palabra, "entrada": entrada, "boton": boton, "cargar": cargar, "marco": tile}

        reproduccion = self._con_tema(tk.Frame(tarjeta), bg="superficie")
        reproduccion.grid(row=2, column=0, columnspan=2, sticky="ew")
        reproduccion.columnconfigure(0, weight=1)
        self.progreso = self._con_tema(tk.Canvas(reproduccion, height=6, highlightthickness=0), bg="superficie")
        self.progreso.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.progreso.bind("<Configure>", lambda _e: self._dibujar_progreso(0) if not self.sesion_audio else None)
        self.boton_detener = self._boton(reproduccion, "■  Detener", self.detener_todo, state="disabled")
        self.boton_detener.grid(row=0, column=1, rowspan=2)
        self.audio_estado = self._etiqueta(reproduccion, "Elige un idioma para escuchar", 9, fg="suave", anchor="w")
        self.audio_estado.grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _crear_edicion(self, padre) -> None:
        # Las palabras y los audios se editan en cada idioma; aquí quedan las acciones generales.
        self.edicion = self._tarjeta(padre, padx=18, pady=12)
        textos = self._con_tema(tk.Frame(self.edicion), bg="superficie")
        textos.pack(side="left")
        self._etiqueta(textos, "EDICIÓN DE CARTA", 9, "bold", fg="acento").pack(anchor="w")
        self._etiqueta(textos, "Contenido y tarjeta", 12, "bold").pack(anchor="w", pady=(2, 0))
        self.etiqueta_tarjeta = self._etiqueta(textos, "Tarjeta RFID: —", 9, fg="suave")
        self.etiqueta_tarjeta.pack(anchor="w")
        acciones = self._con_tema(tk.Frame(self.edicion), bg="superficie")
        acciones.pack(side="right")
        grupo_rfid = self._con_tema(tk.Frame(acciones, padx=10), bg="panel")
        grupo_rfid.pack(side="left", padx=(0, 8))
        self._etiqueta(grupo_rfid, "TARJETA RFID", 8, "bold", fg="suave", bg="panel").pack(anchor="w", pady=(5, 0))
        fila_rfid = self._con_tema(tk.Frame(grupo_rfid), bg="panel")
        fila_rfid.pack(pady=(2, 6))
        self.boton_grabar = self._boton(fila_rfid, "✎ Grabar", self.grabar_tarjeta, pady=5, padx=9)
        self.boton_grabar.pack(side="left")
        self.boton_asignar = self._boton(fila_rfid, "Asignar", self.asignar_tarjeta, pady=5, padx=9)
        self.boton_asignar.pack(side="left", padx=(5, 0))
        self._boton(fila_rfid, "Quitar", self.quitar_tarjeta, pady=5, padx=9).pack(side="left", padx=(5, 0))
        grupo_archivos = self._con_tema(tk.Frame(acciones, padx=10), bg="panel")
        grupo_archivos.pack(side="left", padx=(0, 8))
        self._etiqueta(grupo_archivos, "RECURSOS", 8, "bold", fg="suave", bg="panel").pack(anchor="w", pady=(5, 0))
        self._boton(grupo_archivos, "▣ Imagen", lambda: self.cargar("imagen"), pady=5, padx=10).pack(pady=(2, 6))
        self._boton(acciones, "✓  Guardar", self.guardar_textos, "acento", pady=9).pack(side="left", padx=(0, 8))
        self._boton(acciones, "🗑", self.eliminar_carta, ("#E03E3E", "#C53030"), pady=9, padx=11).pack(side="left")

    # ---------- datos ----------
    def cambiar_nivel(self) -> None:
        superior = self.nivel.get() == "superior"
        juego = self.nivel.get() == "juego"
        # Juego: sin lista ni edición, solo la tarjeta en grande.
        if juego:
            self.lateral.grid_remove()
            self.titulo.configure(font=(FUENTE, 38, "bold"))
            self._esperar_tarjeta_juego()
        else:
            self.lateral.grid()
            self.titulo.configure(font=(FUENTE, 26, "bold"))
        if superior:
            self.edicion.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        else:
            self.edicion.grid_remove()
        for tile in self.tiles.values():
            if superior:
                tile["palabra"].pack_forget()
                tile["entrada"].pack(fill="x", pady=(4, 0))
                tile["cargar"].pack(side="left", padx=(6, 0))
            else:
                tile["entrada"].pack_forget()
                tile["cargar"].pack_forget()
                tile["palabra"].pack(fill="x")
        # Al ocultar columnas, "nombre" se estira; hay que devolverle su ancho para que quepan las demás.
        self.tabla.column("nombre", width=96 if superior else 260)
        self.tabla.configure(displaycolumns="#all" if superior else ("nombre",))
        self.instruccion.configure(text=INSTRUCCIONES[self.nivel.get()])

    def _esperar_tarjeta_juego(self) -> None:
        """Pantalla inicial del modo Juego; conecta el lector si hace falta."""
        self.detener_todo()
        self.carta_actual = None
        self.tabla.selection_remove(*self.tabla.selection())
        self.etiqueta_carta.configure(text="MODO JUEGO")
        self.titulo.configure(text="Acerca una tarjeta")
        for tile in self.tiles.values():
            tile["palabra"].configure(text="—")
            self._habilitar(tile["boton"], False)
        self._imagen_pil = None
        self.imagen_tk = None
        self.imagen.configure(image="", text="Esperando una tarjeta en el lector…")
        if not self.lector:
            if listar_puertos():
                self.alternar_lector()
            else:
                self.estado.configure(text="⚠  Conecta el ESP32 por USB para jugar con tarjetas.")

    def importar(self) -> None:
        try:
            totales = importar_archivos(self.conexion)
            self.recargar()
            self.estado.configure(text="Importado · " + " · ".join(f"{v} {k}" for k, v in totales.items()))
        except Exception as error:
            messagebox.showerror("No se pudo importar", str(error))

    def importar_audios_ingles(self) -> None:
        """Carga los MP3 de inglés sin modificar los demás recursos."""
        try:
            total = importar_audios_ingles(self.conexion)
            self.recargar()
            self.estado.configure(text=f"Importados o actualizados {total} audios en inglés.")
        except Exception as error:
            messagebox.showerror("No se pudieron importar los audios en inglés", str(error))

    def nueva_carta(self) -> None:
        """Da de alta una carta vacía para completarla en el modo Edición."""
        nombre = simpledialog.askstring(
            "Nueva carta", "Palabra en español:", parent=self
        )
        if nombre is None:
            return
        try:
            carta_id = crear_carta(self.conexion, nombre)
        except ValueError as error:
            messagebox.showerror("No se pudo crear la carta", str(error), parent=self)
            return
        self.nivel.set("superior")
        self.cambiar_nivel()
        self.recargar()
        self.carta_actual = carta_id
        self.tabla.selection_set(str(carta_id))
        self.tabla.see(str(carta_id))
        self.seleccionar()
        self.estado.configure(text=f"Carta «{nombre.strip()}» creada. Carga ahora imagen, audios y tarjeta RFID.")

    def recargar(self) -> None:
        self.filas = {fila["id"]: dict(fila) for fila in resumen(self.conexion)}
        self._llenar_tabla()
        self._dibujar_estadisticas()

    def _llenar_tabla(self) -> None:
        actual = str(self.carta_actual) if self.carta_actual else None
        filtro = clave(self.busqueda.get())
        self.tabla.delete(*self.tabla.get_children())
        visibles = 0
        for fila in self.filas.values():
            if filtro and not any(filtro in clave(fila[c] or "") for c in ("nombre", "mazahua", "ingles", "uid_rfid")):
                continue
            marca = lambda campo: "✓" if fila[campo] else "·"
            valores = (fila["nombre"].capitalize(), marca("tiene_imagen"), marca("tiene_espanol"),
                       marca("tiene_mazahua"), marca("tiene_ingles"), marca("uid_rfid"))
            self.tabla.insert("", "end", iid=str(fila["id"]), values=valores, tags=("par",) if visibles % 2 else ())
            visibles += 1
        self.contador.configure(text=f"{visibles} de {len(self.filas)}" if filtro else f"{len(self.filas)} cartas")
        if actual and self.tabla.exists(actual):
            self.tabla.selection_set(actual)
            self.tabla.see(actual)

    def _dibujar_estadisticas(self) -> None:
        if not hasattr(self, "estadisticas"):
            return
        t, lienzo = self.tema, self.estadisticas
        lienzo.delete("all")
        total = len(self.filas)
        ancho = max(200, lienzo.winfo_width())
        mitad = ancho / 2
        datos = (("Imagen", "tiene_imagen", "#8B5CF6"),) + tuple(
            (IDIOMA_UI[i][0], campo, IDIOMA_UI[i][1]) for i, campo in zip(IDIOMAS, ("tiene_espanol", "tiene_mazahua", "tiene_ingles")))
        for indice, (nombre, campo, color) in enumerate(datos):
            cantidad = sum(1 for fila in self.filas.values() if fila[campo])
            x, y = (indice % 2) * mitad, (indice // 2) * 34
            derecha = x + mitad - (10 if indice % 2 == 0 else 0)
            lienzo.create_text(x, y + 8, text=nombre, anchor="w", fill=t["suave"], font=(FUENTE, 9, "bold"))
            lienzo.create_text(derecha, y + 8, text=f"{cantidad}/{total}", anchor="e", fill=t["texto"], font=(FUENTE, 9))
            lienzo.create_rectangle(x, y + 19, derecha, y + 24, fill=t["borde"], outline="")
            if total:
                lienzo.create_rectangle(x, y + 19, x + (derecha - x) * cantidad / total, y + 24, fill=color, outline="")

    def seleccionar(self, _evento=None) -> None:
        seleccion = self.tabla.selection()
        if not seleccion:
            return
        self.carta_actual = int(seleccion[0])
        carta = obtener_carta(self.conexion, self.carta_actual)
        fila = self.filas[self.carta_actual]
        uid = carta["uid_rfid"]
        if self.nivel.get() == "juego":
            self.etiqueta_carta.configure(text=f"TARJETA {uid}" if uid else "MODO JUEGO")
        else:
            self.etiqueta_carta.configure(text=f"CARTA  ·  TARJETA {uid}" if uid else "CARTA")
        self.etiqueta_tarjeta.configure(text=f"Tarjeta RFID: {uid}" if uid else "Tarjeta RFID: sin asignar")
        self.titulo.configure(text=carta["nombre"].capitalize())
        self.instruccion.configure(text=INSTRUCCIONES[self.nivel.get()])
        palabras = {"español": carta["nombre"], "mazahua": carta["mazahua"], "inglés": carta["ingles"]}
        disponibles = {"español": fila["tiene_espanol"], "mazahua": fila["tiene_mazahua"], "inglés": fila["tiene_ingles"]}
        for idioma, tile in self.tiles.items():
            tile["palabra"].configure(text=palabras[idioma] or "—")
            self._habilitar(tile["boton"], bool(disponibles[idioma]))
            self.textos[idioma].set(palabras[idioma])
        medio = obtener_medio(self.conexion, self.carta_actual, "imagen")
        self._mostrar_imagen(Image.open(BytesIO(medio["contenido"])) if medio else None)

    # ---------- imagen ----------
    def _redimensionar_previa(self, _evento=None) -> None:
        self._programar_render()
        self._dibujar_ambiente_imagen()

    def _dibujar_ambiente_imagen(self) -> None:
        """Dibuja manchas de color y órbitas suaves bajo la vista previa."""
        if not hasattr(self, "ambiente_imagen"):
            return
        lienzo = self.ambiente_imagen
        ancho, alto = max(1, lienzo.winfo_width()), max(1, lienzo.winfo_height())
        fase = self._fase_ambiente
        lienzo.delete("ambiente")
        # El tramado mantiene un efecto difuso compatible con Tkinter nativo.
        desplazamiento = ((fase % 160) - 80) / 80
        colores = ("#B9C6FF", "#8EE3D2", "#FFD0AA") if not self.modo_oscuro else ("#405291", "#1B746C", "#824D40")
        posiciones = ((.08 + desplazamiento * .025, .10, .45), (.66, .55 + desplazamiento * .03, .38),
                      (.30 - desplazamiento * .02, .82, .28))
        for color, (x, y, escala) in zip(colores, posiciones):
            radio = min(ancho, alto) * escala
            lienzo.create_oval(x * ancho - radio, y * alto - radio, x * ancho + radio, y * alto + radio,
                               fill=color, outline="", stipple="gray25", tags="ambiente")
        # Líneas orbitales muy tenues: dan movimiento incluso antes de cargar una imagen.
        centro_x, centro_y = ancho / 2, alto / 2
        for indice in range(3):
            margen = 25 + indice * 18 + abs(desplazamiento) * 6
            lienzo.create_oval(margen, margen, ancho - margen, alto - margen,
                               outline=self.tema["borde"], width=1, tags="ambiente")
        lienzo.tag_lower("ambiente")
        if hasattr(self, "imagen"):
            self.imagen.lift()

    def _animar_ambiente_imagen(self) -> None:
        if not self.winfo_exists() or not hasattr(self, "ambiente_imagen"):
            return
        self._fase_ambiente = (self._fase_ambiente + 1) % 160
        self._dibujar_ambiente_imagen()
        self.after(90, self._animar_ambiente_imagen)

    def _resaltar_tile(self, tile: tk.Widget, activo: bool) -> None:
        """Microinteracción de hover para que las tarjetas no se sientan estáticas."""
        tile.configure(highlightbackground=self.tema["acento"] if activo else self.tema["borde"],
                       highlightcolor=self.tema["acento"] if activo else self.tema["borde"])

    def _mostrar_imagen(self, imagen: Image.Image | None) -> None:
        try:
            self._imagen_pil = imagen.convert("RGBA") if imagen else None
        except OSError:
            self._imagen_pil = None
        if self._imagen_pil is None:
            self.imagen_tk = None
            self.imagen.configure(image="", text="Esta carta no tiene imagen")
        else:
            self._render_imagen()
        self.imagen.lift()
        # Breve resalte del marco al cambiar de carta.
        self.marco_imagen.configure(highlightbackground=self.tema["acento"])
        self.after(350, lambda: self.marco_imagen.configure(highlightbackground=self.tema["borde"]))

    def _programar_render(self) -> None:
        """Al redimensionar la ventana se re-escala la imagen una sola vez (debounce)."""
        if self._render_pendiente:
            self.after_cancel(self._render_pendiente)
        self._render_pendiente = self.after(60, self._render_imagen)

    def _render_imagen(self) -> None:
        self._render_pendiente = None
        if self._imagen_pil is None:
            return
        # Mantiene una vista previa completa y proporcionada: nunca recorta la
        # imagen ni la amplía hasta robar espacio a los campos de edición.
        ancho = min(380, max(80, self.marco_imagen.winfo_width() - 36))
        alto = min(280, max(80, self.marco_imagen.winfo_height() - 48))
        ajustada = ImageOps.contain(self._imagen_pil, (ancho, alto), Image.Resampling.LANCZOS)
        self.imagen_tk = ImageTk.PhotoImage(ajustada)
        self.imagen.configure(image=self.imagen_tk, text="")

    # ---------- audio ----------
    def reproducir_secuencia(self, idiomas: list[str]) -> None:
        """Reproduce varios audios uno tras otro; cada uno se detiene solo al terminar."""
        self.cola_audio = list(idiomas)
        self._siguiente_audio()

    def _siguiente_audio(self) -> None:
        if self.cola_audio:
            self.reproducir(self.cola_audio.pop(0), desde_cola=True)

    def detener_todo(self) -> None:
        self.cola_audio = []
        self.detener()

    def reproducir(self, idioma: str, desde_cola: bool = False) -> None:
        if not desde_cola:
            self.cola_audio = []  # un clic manual interrumpe la secuencia
        if not self.carta_actual:
            return
        medio = obtener_medio(self.conexion, self.carta_actual, idioma)
        if not medio:
            return
        carpeta = Path(tempfile.gettempdir()) / "loteria_mazahua_audio"
        carpeta.mkdir(exist_ok=True)
        archivo = carpeta / f"{uuid4().hex}{medio['extension']}"
        archivo.write_bytes(medio["contenido"])
        self._iniciar_audio(archivo, IDIOMA_UI[idioma][0], temporal=True, idioma=idioma)

    def _iniciar_audio(self, archivo: Path, etiqueta: str, temporal: bool, idioma: str | None = None) -> None:
        self.detener()
        self.archivo_audio = archivo
        self.audio_temporal = temporal
        self._resaltar_idioma(idioma)
        try:
            # ffpyplayer utiliza el motor de audio dentro de este proceso.
            self.reproductor = MediaPlayer(str(self.archivo_audio), ff_opts={"vn": True, "loop": 0})
            self.reproductor.set_pause(False)
            self.sesion_audio = uuid4().hex
            self.inicio_audio = time.monotonic()
            self.duracion_audio = 0.0
            sesion = self.sesion_audio
            self._habilitar(self.boton_detener, True)
            self.audio_estado.configure(text=f"Reproduciendo · {etiqueta}")
            # La duración se consulta una vez que el motor termina de cargar
            # metadatos. Así se detiene de forma segura al finalizar el audio.
            self.after(180, lambda s=sesion: self._programar_fin(s, 0))
            self.after(100, lambda s=sesion: self._actualizar_progreso(s))
        except Exception as error:
            self.detener()
            messagebox.showerror("No se pudo reproducir", str(error))

    def _programar_fin(self, sesion: str | None, intento: int) -> None:
        if not sesion or sesion != self.sesion_audio or not self.reproductor:
            return
        duracion = float(self.reproductor.get_metadata().get("duration") or 0)
        if duracion > 0:
            self.duracion_audio = duracion
            self.after(max(50, int(duracion * 1000) + 120), lambda: self._finalizar_audio(sesion))
        elif intento < 12:
            self.after(150, lambda: self._programar_fin(sesion, intento + 1))
        else:
            # Límite de seguridad si un archivo no informa duración.
            self.after(30000, lambda: self._finalizar_audio(sesion))

    def _actualizar_progreso(self, sesion: str | None) -> None:
        if not sesion or sesion != self.sesion_audio or not self.reproductor:
            return
        avance = time.monotonic() - self.inicio_audio
        self._dibujar_progreso(min(1.0, avance / self.duracion_audio) if self.duracion_audio else 0.05)
        self.after(50, lambda: self._actualizar_progreso(sesion))

    def _dibujar_progreso(self, porcentaje: float) -> None:
        ancho = max(1, self.progreso.winfo_width())
        self.progreso.delete("all")
        self.progreso.create_rectangle(0, 0, ancho, 6, fill=self.tema["borde"], outline="")
        if porcentaje:
            self.progreso.create_rectangle(0, 0, ancho * porcentaje, 6, fill=self.tema["progreso"], outline="")

    def _resaltar_idioma(self, idioma: str | None) -> None:
        """Marca con el color del idioma la tarjeta que está sonando."""
        self.idioma_sonando = idioma
        for nombre, tile in self.tiles.items():
            if nombre == idioma:
                color = IDIOMA_UI[nombre][1]
                tile["marco"].configure(highlightthickness=2, highlightbackground=color, highlightcolor=color)
            else:
                tile["marco"].configure(highlightthickness=1, highlightbackground=self.tema["borde"],
                                        highlightcolor=self.tema["borde"])

    def _finalizar_audio(self, sesion: str | None) -> None:
        """El audio terminó: se libera el reproductor (se detiene solo) y sigue la secuencia si la hay."""
        if sesion != self.sesion_audio:
            return
        self.detener()
        if self.cola_audio:
            self.audio_estado.configure(text=f"Sigue · {IDIOMA_UI[self.cola_audio[0]][0]}")
            self.after(450, self._siguiente_audio)  # pequeña pausa entre idiomas
        else:
            self.audio_estado.configure(text="Listo. Puedes escucharlo otra vez o elegir otro idioma.")

    def detener(self) -> None:
        self.sesion_audio = None
        self.duracion_audio = 0.0
        if self.reproductor:
            self.reproductor.close_player()
            self.reproductor = None
        self._habilitar(self.boton_detener, False)
        self._resaltar_idioma(None)
        self.audio_estado.configure(text="Elige un idioma para escuchar")
        self._dibujar_progreso(0)
        if self.archivo_audio and self.audio_temporal:
            try:
                self.archivo_audio.unlink(missing_ok=True)
            except OSError:
                pass
        self.archivo_audio = None

    def _atajo_teclado(self, evento) -> None:
        # No interceptar teclas mientras se escribe en un campo.
        if evento.keysym in ATAJOS and not isinstance(evento.widget, (tk.Entry, ttk.Entry)):
            self.reproducir(ATAJOS[evento.keysym])

    # ---------- edición (modo media superior) ----------
    def _requiere_carta(self) -> bool:
        if not self.carta_actual:
            messagebox.showinfo("Edición", "Selecciona primero una carta de la lista.")
        return bool(self.carta_actual)

    def guardar_textos(self) -> None:
        if not self._requiere_carta():
            return
        try:
            guardar_textos(self.conexion, self.carta_actual, *(self.textos[i].get() for i in IDIOMAS))
        except ValueError as error:
            messagebox.showerror("No se pudo guardar", str(error))
            return
        self.recargar()
        self.seleccionar()
        self.estado.configure(text="Palabras guardadas.")

    def eliminar_carta(self) -> None:
        """Elimina la carta seleccionada y sus medios de SQLite tras confirmarlo."""
        if not self._requiere_carta():
            return
        nombre = self.filas[self.carta_actual]["nombre"]
        mensaje = (
            f"¿Eliminar la carta «{nombre}» y todos sus recursos "
            "(imagen, audios y UID)?\nEsta acción no se puede deshacer."
        )
        if not messagebox.askyesno("Eliminar carta", mensaje, parent=self):
            return
        try:
            eliminar_carta(self.conexion, self.carta_actual)
        except Exception as error:
            messagebox.showerror("No se pudo eliminar", str(error), parent=self)
            return
        self.carta_actual = None
        self.recargar()
        self.estado.configure(text=f"Carta «{nombre}» eliminada.")

    def cargar(self, tipo: str) -> None:
        """Sustituye la imagen o el audio de un idioma de la carta seleccionada."""
        if not self._requiere_carta():
            return
        familia = "imagen" if tipo == "imagen" else "audio"
        patron = " ".join(f"*{e}" for e in sorted(EXTENSIONES[familia]))
        archivo = filedialog.askopenfilename(title=f"Elegir {familia}", filetypes=[(familia.capitalize(), patron)])
        if not archivo:
            return
        try:
            cargar_medio(self.conexion, self.carta_actual, tipo, archivo)
        except (ValueError, OSError) as error:
            messagebox.showerror("No se pudo cargar", str(error))
            return
        self.recargar()
        self.seleccionar()
        nombre = "Imagen" if tipo == "imagen" else f"Audio en {IDIOMA_UI[tipo][0]}"
        self.estado.configure(text=f"{nombre} guardado en SQLite.")

    # ---------- lector RFID: cada carta puede tener una tarjeta (carta.uid_rfid) ----------
    def alternar_lector(self) -> bool:
        """Conecta o desconecta el lector. Devuelve True si queda conectado."""
        if self.lector:
            self.lector.detener()
            self.lector = None
            self.boton_rfid.configure(text="◉  Conectar lector")
            self.estado.configure(text="Lector desconectado.")
            return False
        puertos = listar_puertos()
        if not puertos:
            messagebox.showinfo("Lector RFID", "No se detectó ningún puerto serie. Conecta el ESP32 e instala pyserial.")
            return False
        puerto = puertos[0]  # con varios puertos se usa el primero
        self.lector = LectorRFID(puerto, self.lecturas.put, lambda msg: self.lecturas.put({"error": msg}),
                                 lambda es_error, msg: self.lecturas.put({"estado": msg, "es_error": es_error}))
        self.lector.start()
        self.boton_rfid.configure(text="●  Lector conectado")
        self.estado.configure(text=f"Acerca una tarjeta al lector ({puerto})")
        return True

    def asignar_tarjeta(self) -> None:
        """Espera la siguiente tarjeta del lector; sin lector, permite escribir el UID."""
        if self.esperando_tarjeta:
            self._fin_espera("Asignación cancelada.")
            return
        if not self._requiere_carta():
            return
        if self.lector or (listar_puertos() and self.alternar_lector()):
            self.esperando_tarjeta = True
            self.boton_asignar.configure(text="✕  Cancelar")
            nombre = self.filas[self.carta_actual]["nombre"]
            self.estado.configure(text=f"Pasa la tarjeta por el lector para asignarla a «{nombre}»…")
            return
        uid = simpledialog.askstring("Asignar tarjeta", "No hay lector conectado.\nEscribe el UID de la tarjeta:", parent=self)
        if uid:
            self._vincular(uid)

    def quitar_tarjeta(self) -> None:
        if self._requiere_carta() and self.filas[self.carta_actual]["uid_rfid"]:
            asignar_uid(self.conexion, self.carta_actual, None)
            self.recargar()
            self.seleccionar()
            self.estado.configure(text="Tarjeta desvinculada.")

    def _vincular(self, uid: str) -> None:
        try:
            asignar_uid(self.conexion, self.carta_actual, uid)
        except ValueError as error:
            messagebox.showwarning("Tarjeta ya registrada", str(error))
            return
        self.recargar()
        self.seleccionar()
        self.estado.configure(text=f"Tarjeta asignada a «{self.filas[self.carta_actual]['nombre']}».")

    def _fin_espera(self, mensaje: str) -> None:
        self.esperando_tarjeta = False
        self.boton_asignar.configure(text="◉  Asignar")
        self.estado.configure(text=mensaje)

    def grabar_tarjeta(self) -> None:
        """Escribe en una tarjeta física las palabras guardadas de la carta y la liga a ella."""
        if self.grabando_carta:
            if self.lector:
                self.lector.enviar("CANCELAR")
            self._fin_grabacion("Grabación cancelada.")
            return
        if not self._requiere_carta():
            return
        if not (self.lector or (listar_puertos() and self.alternar_lector())):
            messagebox.showinfo("Grabar tarjeta", "Conecta el lector RFID para grabar tarjetas.")
            return
        carta = obtener_carta(self.conexion, self.carta_actual)
        if any(self.textos[i].get().strip() != (carta[c] or "") for i, c in zip(IDIOMAS, ("nombre", "mazahua", "ingles"))):
            if not messagebox.askyesno("Grabar tarjeta", "Hay cambios sin guardar. Se grabará lo que está en la base.\n¿Continuar?"):
                return
        recortadas = [p for p in (carta["nombre"], carta["mazahua"], carta["ingles"]) if p and recortar_16(p) != p]
        if recortadas:
            self.estado.configure(text="Las palabras largas se recortan a 16 bytes: " + ", ".join(recortadas))
        # El ESP32 acaba de reiniciarse si el lector se conectó ahora: se reintenta hasta que el puerto esté abierto.
        self.grabando_carta = carta["id"]
        self.boton_grabar.configure(text="✕  Cancelar")
        self._enviar_grabacion(comando_grabar(carta["nombre"], carta["mazahua"], carta["ingles"]), 0)

    def _enviar_grabacion(self, comando: str, intento: int) -> None:
        if not self.grabando_carta or not self.lector:
            return
        if self.lector.enviar(comando):
            self.estado.configure(text=f"Acerca la tarjeta al lector para grabar «{self.filas[self.grabando_carta]['nombre']}»…")
        elif intento < 30:
            self.after(100, lambda: self._enviar_grabacion(comando, intento + 1))
        else:
            self._fin_grabacion("⚠  No se pudo hablar con el ESP32.")

    def _respuesta_grabacion(self, respuesta: dict) -> None:
        if not self.grabando_carta or respuesta["grabacion"] == "esperando":
            return
        carta_id = self.grabando_carta
        nombre = self.filas[carta_id]["nombre"]
        if respuesta["grabacion"] == "ok":
            anterior = reasignar_uid(self.conexion, carta_id, respuesta["uid"])
            self.recargar()
            if self.carta_actual == carta_id:
                self.seleccionar()
            extra = f" (antes era de «{anterior}»)" if anterior else ""
            self._fin_grabacion(f"✓  Tarjeta {respuesta['uid']} grabada y asignada a «{nombre}»{extra}.")
        elif respuesta["grabacion"] == "error":
            self._fin_grabacion(f"⚠  No se grabó «{nombre}»: {respuesta['motivo']}.")
        else:
            self._fin_grabacion("Grabación cancelada.")

    def _fin_grabacion(self, mensaje: str) -> None:
        self.grabando_carta = None
        self.boton_grabar.configure(text="✎  Grabar tarjeta")
        if mensaje:
            self.estado.configure(text=mensaje)

    def _revisar_lecturas(self) -> None:
        while not self.lecturas.empty():
            lectura = self.lecturas.get()
            if "error" in lectura:
                self.lector = None
                self.boton_rfid.configure(text="◉  Conectar lector")
                if self.esperando_tarjeta:
                    self._fin_espera("")
                if self.grabando_carta:
                    self._fin_grabacion("")
                self.estado.configure(text=lectura["error"])
            elif "grabacion" in lectura:
                self._respuesta_grabacion(lectura)
            elif "estado" in lectura:  # diagnóstico del ESP32 (RC522 / Micro SD)
                self.estado.configure(text=("⚠  ESP32: " if lectura["es_error"] else "ESP32: ") + lectura["estado"])
            elif self.esperando_tarjeta and self.carta_actual:
                self._fin_espera("")
                self._vincular(lectura["uid"])
            else:
                self.procesar_lectura(lectura)
        self._id_lecturas = self.after(100, self._revisar_lecturas)

    def procesar_lectura(self, lectura: dict) -> None:
        """Empareja la tarjeta con la base (ver ``emparejar_lectura``) y la lleva al juego."""
        uid = lectura["uid"]
        palabras = [lectura["espanol"], lectura["mazahua"], lectura["ingles"]]
        grabada = next((p for p in palabras if p), "")
        carta, estado = emparejar_lectura(self.conexion, uid, palabras)
        nombre = carta["nombre"] if carta else ""
        mensajes = {
            "valida": f"Tarjeta {uid} · «{nombre}»",
            "asociada": f"✓  Tarjeta {uid} asociada automáticamente a «{nombre}».",
            "distinta": f"⚠  La tarjeta {uid} es de «{nombre}», pero tiene grabado «{grabada}». Se usa la base.",
            "ocupada": f"⚠  «{nombre}» ya tiene la tarjeta {carta['uid_rfid'] if carta else ''}. "
                       f"La tarjeta {uid} no se asoció; quita la anterior en Edición para cambiarla.",
            "creada": f"✓  Tarjeta nueva {uid}: se creó la carta «{nombre}» con sus palabras. Falta su imagen y audio.",
            "nueva": f"Tarjeta nueva {uid} sin palabra grabada: quedó registrada; asígnala en el modo Edición.",
        }
        if estado in ("asociada", "creada"):
            self.recargar()
        if carta:
            self.mostrar_carta(carta["id"])
        self.estado.configure(text=mensajes[estado])

    def mostrar_carta(self, carta_id: int) -> None:
        """Muestra la carta leída. En modo Juego suenan todos sus idiomas; si no, solo el mazahua."""
        if self.busqueda.get():
            self.busqueda.set("")  # la carta podría estar oculta por el filtro
        iid = str(carta_id)
        self.tabla.selection_set(iid)
        self.tabla.see(iid)
        self.seleccionar()
        fila = self.filas[carta_id]
        campos = {"mazahua": "tiene_mazahua", "español": "tiene_espanol", "inglés": "tiene_ingles"}
        disponibles = [i for i in ORDEN_JUEGO if fila[campos[i]]]
        if self.nivel.get() == "juego":
            self.etiqueta_carta.configure(text=f"TARJETA {fila['uid_rfid']}" if fila["uid_rfid"] else "MODO JUEGO")
            self.instruccion.configure(text=INSTRUCCIONES["juego"])
            self.reproducir_secuencia(disponibles)
            if not disponibles:
                self.audio_estado.configure(text="Esta carta aún no tiene audios.")
        elif disponibles:
            self.reproducir(disponibles[0])

    def cerrar(self) -> None:
        if self._id_lecturas:
            self.after_cancel(self._id_lecturas)
        if self.lector:
            self.lector.detener()
        self.detener()
        self.conexion.close()
        super().destroy()


if __name__ == "__main__":
    AplicacionLoteria().mainloop()
