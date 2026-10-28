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

from base_datos import (EXTENSIONES, IDIOMAS, RUTA_BD, asignar_uid, cargar_medio, conectar, emparejar_lectura,
                        crear_esquema, guardar_textos, importar_archivos, obtener_carta, obtener_medio,
                        reasignar_uid, resumen)
from catalogo_loteria import clave
from lector_rfid import LectorRFID, comando_grabar, listar_puertos, recortar_16

FUENTE = "Segoe UI"
TEMAS = {
    "claro": {
        "fondo": "#F3F5F9", "superficie": "#FFFFFF", "panel": "#F6F7FB", "texto": "#1E2533", "suave": "#667085",
        "borde": "#E3E7EF", "lienzo": "#FAFBFD", "header": "#4B3B9A", "header_suave": "#D9D2FF",
        "header_boton": "#5D4DB0", "header_activo": "#6E5FC4", "acento": "#4B3B9A", "acento_activo": "#3A2D80",
        "seleccion": "#E9E5FF", "seleccion_texto": "#2B1F6B", "progreso": "#12927A",
    },
    "oscuro": {
        "fondo": "#0F1420", "superficie": "#171E2C", "panel": "#1D2536", "texto": "#EEF1F7", "suave": "#98A2B3",
        "borde": "#2A3446", "lienzo": "#111827", "header": "#241B4D", "header_suave": "#BDB3F5",
        "header_boton": "#33296A", "header_activo": "#44398A", "acento": "#7C6BF0", "acento_activo": "#6352E0",
        "seleccion": "#3B3277", "seleccion_texto": "#FFFFFF", "progreso": "#34C9A5",
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

    def _tarjeta(self, padre, **opciones) -> tk.Frame:
        """Superficie con borde fino, base de todos los paneles."""
        return self._con_tema(tk.Frame(padre, highlightthickness=1, bd=0, **opciones),
                       bg="superficie", highlightbackground="borde", highlightcolor="borde")

    def _etiqueta(self, padre, texto="", tamano=10, peso="normal", fg="texto", bg="superficie", **opciones) -> tk.Label:
        return self._con_tema(tk.Label(padre, text=texto, font=(FUENTE, tamano, peso), **opciones), bg=bg, fg=fg)

    def _boton(self, padre, texto, comando, estilo: object = "secundario", **opciones) -> tk.Button:
        """``estilo``: "secundario", "acento", "header" o una tupla (color, color_hover)."""
        opciones = {"font": (FUENTE, 10, "bold"), "padx": 14, "pady": 8, **opciones}
        boton = tk.Button(padre, text=texto, command=comando, relief="flat", bd=0, cursor="hand2", **opciones)
        self._botones[boton] = estilo
        boton.bind("<Enter>", lambda _e: self._pintar_boton(boton, encima=True))
        boton.bind("<Leave>", lambda _e: self._pintar_boton(boton))
        return boton

    def _pintar_boton(self, boton: tk.Button, encima: bool = False) -> None:
        t, estilo = self.tema, self._botones[boton]
        if estilo == "secundario":
            base, activo, fg = t["panel"], t["borde"], t["texto"]
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
                         rowheight=34, font=(FUENTE, 11), borderwidth=0, relief="flat")
        estilo.configure("Treeview.Heading", background=t["panel"], foreground=t["suave"], font=(FUENTE, 9, "bold"),
                         relief="flat", borderwidth=0, padding=(8, 6))
        estilo.map("Treeview", background=[("selected", t["seleccion"])], foreground=[("selected", t["seleccion_texto"])])
        estilo.map("Treeview.Heading", background=[("active", t["borde"])])
        estilo.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # sin marco 3D
        estilo.configure("TEntry", fieldbackground=t["panel"], foreground=t["texto"], insertcolor=t["texto"],
                         bordercolor=t["borde"], lightcolor=t["borde"], darkcolor=t["borde"], padding=(8, 6))
        estilo.map("TEntry", bordercolor=[("focus", t["acento"])], lightcolor=[("focus", t["acento"])])
        estilo.configure("Vertical.TScrollbar", troughcolor=t["superficie"], background=t["borde"], bordercolor=t["superficie"],
                         arrowcolor=t["suave"], lightcolor=t["borde"], darkcolor=t["borde"])
        self.tabla.tag_configure("par", background=t["panel"])
        self._dibujar_estadisticas()
        self._dibujar_progreso(0)

    # ---------- construcción de la interfaz ----------
    def _crear_interfaz(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._crear_encabezado()
        self._crear_barra()
        cuerpo = self._con_tema(tk.Frame(self, padx=20, pady=16), bg="fondo")
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
        encabezado = self._con_tema(tk.Frame(self, padx=24, pady=14), bg="header")
        encabezado.grid(row=0, column=0, sticky="ew")
        marca = self._con_tema(tk.Frame(encabezado), bg="header")
        marca.pack(side="left")
        self._etiqueta(marca, "Lotería Mazahua", 20, "bold", fg="#FFFFFF", bg="header").pack(anchor="w")
        self._etiqueta(marca, "Aprende jugando  ·  Español  ·  Mazahua  ·  English", 10, fg="header_suave", bg="header").pack(anchor="w")
        self.boton_tema = self._boton(encabezado, "☾  Tema oscuro", self.alternar_tema, "header")
        self.boton_tema.pack(side="right", padx=(8, 0))
        self._boton(encabezado, "⟳  Importar recursos", self.importar, "header").pack(side="right", padx=(8, 0))
        self.boton_rfid = self._boton(encabezado, "◉  Conectar lector", self.alternar_lector, "header")
        self.boton_rfid.pack(side="right")

    def _crear_barra(self) -> None:
        barra = self._con_tema(tk.Frame(self, padx=24, pady=10), bg="superficie")
        barra.grid(row=1, column=0, sticky="ew")
        self._etiqueta(barra, "Modo", 10, "bold", fg="suave").pack(side="left", padx=(0, 10))
        for valor, texto in (("basica", "Primaria"), ("superior", "Media superior · Edición"), ("juego", "▶  Juego · Tarjetas")):
            radio = tk.Radiobutton(barra, text=texto, variable=self.nivel, value=valor, command=self.cambiar_nivel,
                                   indicatoron=False, relief="flat", bd=0, offrelief="flat", cursor="hand2",
                                   font=(FUENTE, 10, "bold"), padx=14, pady=6)
            self._con_tema(radio, bg="panel", fg="texto", selectcolor="seleccion", activebackground="borde", activeforeground="texto")
            radio.pack(side="left", padx=(0, 4))
        self.estado = self._etiqueta(barra, f"Base de datos: {RUTA_BD.name}", 10, fg="suave")
        self.estado.pack(side="right")

    def _crear_lateral(self, padre) -> None:
        lateral = self.lateral = self._tarjeta(padre, width=340, padx=14, pady=14)
        lateral.grid(row=0, column=0, sticky="ns", padx=(0, 16))
        lateral.pack_propagate(False)
        cabecera = self._con_tema(tk.Frame(lateral), bg="superficie")
        cabecera.pack(fill="x")
        self._etiqueta(cabecera, "Cartas", 14, "bold").pack(side="left")
        self.contador = self._etiqueta(cabecera, "", 10, fg="suave")
        self.contador.pack(side="right")
        ttk.Entry(lateral, textvariable=self.busqueda, font=(FUENTE, 11)).pack(fill="x", pady=(10, 4))
        self._etiqueta(lateral, "Buscar en español, mazahua o inglés", 8, fg="suave").pack(anchor="w")
        self.busqueda.trace_add("write", lambda *_: self._llenar_tabla())
        self.estadisticas = self._con_tema(tk.Canvas(lateral, height=66, highlightthickness=0), bg="superficie")
        self.estadisticas.pack(fill="x", pady=(10, 8))
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
        tarjeta = self._tarjeta(padre, padx=24, pady=20)
        tarjeta.grid(row=0, column=0, sticky="nsew")
        # Distribución: imagen grande a la izquierda, los tres idiomas apilados a la derecha.
        tarjeta.columnconfigure(0, weight=1)
        tarjeta.columnconfigure(1, minsize=300)
        tarjeta.rowconfigure(1, weight=1)
        cabecera = self._con_tema(tk.Frame(tarjeta), bg="superficie")
        cabecera.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.etiqueta_carta = self._etiqueta(cabecera, "CARTA", 9, "bold", fg="acento")
        self.etiqueta_carta.pack(anchor="w")
        self.titulo = self._etiqueta(cabecera, "Selecciona una carta", 26, "bold", anchor="w")
        self.titulo.pack(fill="x")
        self.instruccion = self._etiqueta(cabecera, INSTRUCCIONES["basica"], 10, fg="suave", anchor="w")
        self.instruccion.pack(fill="x")

        # La imagen se coloca con place() para que nunca agrande el marco: se adapta a él.
        self.marco_imagen = self._con_tema(tk.Frame(tarjeta, highlightthickness=1, bd=0), bg="lienzo",
                                    highlightbackground="borde", highlightcolor="borde")
        self.marco_imagen.grid(row=1, column=0, sticky="nsew", pady=16, padx=(0, 16))
        self.imagen = self._etiqueta(self.marco_imagen, "Elige una carta de la lista", 13, fg="suave", bg="lienzo")
        self.imagen.place(relx=0.5, rely=0.5, anchor="center")
        self.marco_imagen.bind("<Configure>", lambda _e: self._programar_render())

        idiomas = self._con_tema(tk.Frame(tarjeta), bg="superficie")
        idiomas.grid(row=1, column=1, sticky="nsew", pady=16)
        # Cada idioma: palabra (o campo editable en modo edición) + escuchar (+ cargar audio).
        self.tiles: dict[str, dict[str, tk.Widget]] = {}
        for idioma in IDIOMAS:
            nombre, color, hover, tecla = IDIOMA_UI[idioma]
            tile = self._tarjeta(idiomas)
            tile.pack(fill="x", pady=(0, 10))
            tk.Frame(tile, bg=color, width=4).pack(side="left", fill="y")
            acciones = self._con_tema(tk.Frame(tile, pady=10), bg="superficie")
            acciones.pack(side="right", padx=12)
            boton = self._boton(acciones, "▶  Escuchar", lambda i=idioma: self.reproducir(i), (color, hover), state="disabled")
            boton.pack(side="left")
            cargar = self._boton(acciones, "Cargar audio…", lambda i=idioma: self.cargar(i), font=(FUENTE, 9, "bold"), padx=10)
            texto = self._con_tema(tk.Frame(tile, padx=14, pady=10), bg="superficie")
            texto.pack(side="left", fill="both", expand=True)
            self._etiqueta(texto, f"{nombre.upper()}  ·  tecla {tecla}", 8, "bold", fg=color, anchor="w").pack(fill="x")
            palabra = self._etiqueta(texto, "—", 16, "bold", anchor="w", wraplength=170, justify="left")
            palabra.pack(fill="x")
            entrada = ttk.Entry(texto, textvariable=self.textos[idioma], font=(FUENTE, 12), width=12)
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
        self.edicion = self._tarjeta(padre, padx=20, pady=12)
        textos = self._con_tema(tk.Frame(self.edicion), bg="superficie")
        textos.pack(side="left")
        self._etiqueta(textos, "Editar carta", 12, "bold").pack(anchor="w")
        self.etiqueta_tarjeta = self._etiqueta(textos, "Tarjeta RFID: —", 9, fg="suave")
        self.etiqueta_tarjeta.pack(anchor="w")
        self._boton(self.edicion, "✓  Guardar palabras", self.guardar_textos, "acento").pack(side="right")
        self._boton(self.edicion, "Imagen…", lambda: self.cargar("imagen")).pack(side="right", padx=8)
        self._boton(self.edicion, "Quitar", self.quitar_tarjeta).pack(side="right")
        self.boton_asignar = self._boton(self.edicion, "◉  Asignar", self.asignar_tarjeta)
        self.boton_asignar.pack(side="right", padx=(0, 8))
        self.boton_grabar = self._boton(self.edicion, "✎  Grabar tarjeta", self.grabar_tarjeta)
        self.boton_grabar.pack(side="right", padx=(0, 8))

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
        ancho = max(80, self.marco_imagen.winfo_width() - 32)
        alto = max(80, self.marco_imagen.winfo_height() - 32)
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
