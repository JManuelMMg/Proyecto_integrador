"""Interfaz Qt para Lotería Mazahua; datos y medios permanecen en SQLite."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import time
import queue
from uuid import uuid4

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize, QTimer, QMimeData, QPoint, QRect
from PySide6.QtGui import QPixmap, QIcon, QDrag, QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget, QListView, QAbstractItemView,
    QGraphicsDropShadowEffect,
)
from ffpyplayer.player import MediaPlayer

from base_datos import (
    IDIOMAS, RUTA_BD, cargar_medio, conectar, crear_carta, crear_esquema,
    eliminar_carta, guardar_textos, importar_archivos, importar_audios_ingles,
    obtener_carta, obtener_medio, resumen, emparejar_lectura, reasignar_uid,
)
from lector_rfid import LectorRFID, listar_puertos, comando_grabar, parsear_grabacion


# Tema claro MEJORADO (más vibrante)
ESTILO_CLARO = """
* { font-family: 'Segoe UI', sans-serif; color: #2d1b0e; }
QMainWindow, #main { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fff9f0, stop:1 #f5ebe0); }
#nav { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2d1b0e, stop:1 #1a0f08); min-width: 260px; max-width: 260px; }
#brandMark, #navLabel { color: #ffd700; font-size: 11px; font-weight: 800; letter-spacing: 2px; }
#brandTitle { color: #ffffff; font-family: Georgia, serif; font-size: 28px; font-weight: 900; }
#brandText, #navFoot { color: #d4c4b0; font-size: 13px; }
QPushButton#navButton { color: #e8d8c4; text-align: left; background: transparent; border: 0; border-radius: 12px; padding: 12px 16px; font-size: 15px; font-weight: 600; }
QPushButton#navButton:hover { color: #ffffff; background: rgba(255,215,0,.15); }
QPushButton#navButton:checked { color: #ffd700; background: rgba(255,215,0,.2); border-left: 4px solid #ffd700; }
#eyebrow { color: #8b6f47; font-size: 12px; font-weight: 800; letter-spacing: 2px; }
#title { font-family: Georgia, serif; font-size: 34px; font-weight: 900; color: #2d1b0e; }
#sub { color: #8b6f47; font-size: 15px; }
#card, #editor, #player { background: #ffffff; border-radius: 24px; border: 1px solid #f0e6d8; }
#preview { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fff5e6, stop:1 #ffe8cc); border-radius: 32px; border: 2px solid #ffd700; }
#wordCard { background: #ffffff; border: 2px solid #f0e6d8; border-radius: 20px; }
#wordCard:hover { border: 3px solid #ffd700; background: #fffef5; }
#lang { font-size: 12px; font-weight: 900; letter-spacing: 1.5px; }
#word { font-family: Georgia, serif; font-size: 24px; font-weight: 800; }
#play { color: white; border: 0; border-radius: 24px; font-size: 16px; font-weight: 800; min-width: 48px; min-height: 48px; }
#play:hover { opacity: 0.9; }
#search, #field { background: white; border: 2px solid #e8d8c4; border-radius: 12px; padding: 10px 14px; font-size: 15px; }
#search:focus, #field:focus { border: 3px solid #ffd700; background: #fffef5; }
#list { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fff9f0, stop:1 #f5ebe0); border: 0; border-radius: 24px; padding: 10px; }
#list::item { padding: 12px; border-radius: 14px; margin: 3px; background: white; border: 2px solid transparent; }
#list::item:hover { border: 2px solid #ffd700; background: #fffef5; }
#list::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffd700, stop:1 #ffed4a); color: #2d1b0e; border: 2px solid #ffd700; font-weight: 700; }
#action { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2d1b0e, stop:1 #4a2c17); color: white; border: 0; border-radius: 12px; padding: 12px 18px; font-weight: 800; font-size: 14px; }
#action:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4a2c17, stop:1 #6b3d22); }
#soft { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f5ebe0, stop:1 #e8d8c4); border: 0; border-radius: 12px; padding: 10px 15px; font-weight: 700; }
#soft:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e8d8c4, stop:1 #d4c4b0); }
#danger { background: #fee; color: #c0392b; border: 2px solid #fcc; border-radius: 12px; padding: 10px 14px; font-weight: 700; }
#danger:hover { background: #fcc; }
#configCard { background: #ffffff; border-radius: 24px; padding: 6px; border: 1px solid #f0e6d8; }
#configTitle { font-family: Georgia, serif; font-size: 20px; font-weight: 900; color: #2d1b0e; }
#statusGood { color: #27ae60; font-weight: 800; font-size: 14px; }
#statusMuted { color: #8b6f47; font-size: 14px; }
QScrollBar:vertical { background: #f5ebe0; width: 12px; border-radius: 6px; }
QScrollBar::handle:vertical { background: #ffd700; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #ffed4a; }
"""

# Tema oscuro MEJORADO (más profundo)
ESTILO_OSCURO = """
* { font-family: 'Segoe UI', sans-serif; color: #f5ebe0; }
QMainWindow, #main { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a0f08, stop:1 #0d0804); }
#nav { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d0804, stop:1 #000000); min-width: 260px; max-width: 260px; }
#brandMark, #navLabel { color: #ffd700; font-size: 11px; font-weight: 800; letter-spacing: 2px; }
#brandTitle { color: #ffffff; font-family: Georgia, serif; font-size: 28px; font-weight: 900; }
#brandText, #navFoot { color: #a89a8b; font-size: 13px; }
QPushButton#navButton { color: #d4c4b0; text-align: left; background: transparent; border: 0; border-radius: 12px; padding: 12px 16px; font-size: 15px; font-weight: 600; }
QPushButton#navButton:hover { color: #ffffff; background: rgba(255,215,0,.2); }
QPushButton#navButton:checked { color: #ffd700; background: rgba(255,215,0,.25); border-left: 4px solid #ffd700; }
#eyebrow { color: #c8b8a8; font-size: 12px; font-weight: 800; letter-spacing: 2px; }
#title { font-family: Georgia, serif; font-size: 34px; font-weight: 900; color: #ffffff; }
#sub { color: #c8b8a8; font-size: 15px; }
#card, #editor, #player { background: #2a1f14; border-radius: 24px; border: 1px solid #3a2d20; }
#preview { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a1f14, stop:1 #1f160d); border-radius: 32px; border: 2px solid #ffd700; }
#wordCard { background: #2a1f14; border: 2px solid #3a2d20; border-radius: 20px; }
#wordCard:hover { border: 3px solid #ffd700; background: #3a2d20; }
#lang { font-size: 12px; font-weight: 900; letter-spacing: 1.5px; color: #ffd700; }
#word { font-family: Georgia, serif; font-size: 24px; font-weight: 800; color: #ffffff; }
#play { color: #1a0f08; border: 0; border-radius: 24px; font-size: 16px; font-weight: 800; min-width: 48px; min-height: 48px; }
#play:hover { opacity: 0.9; }
#search, #field { background: #2a1f14; border: 2px solid #3a2d20; border-radius: 12px; padding: 10px 14px; font-size: 15px; color: #f5ebe0; }
#search:focus, #field:focus { border: 3px solid #ffd700; background: #3a2d20; }
#list { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a0f08, stop:1 #0d0804); border: 0; border-radius: 24px; padding: 10px; }
#list::item { padding: 12px; border-radius: 14px; margin: 3px; background: #2a1f14; border: 2px solid transparent; color: #f5ebe0; }
#list::item:hover { border: 2px solid #ffd700; background: #3a2d20; }
#list::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffd700, stop:1 #ffed4a); color: #1a0f08; border: 2px solid #ffd700; font-weight: 700; }
#action { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffd700, stop:1 #ffed4a); color: #1a0f08; border: 0; border-radius: 12px; padding: 12px 18px; font-weight: 800; font-size: 14px; }
#action:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffed4a, stop:1 #fff5cc); }
#soft { background: #3a2d20; border: 0; border-radius: 12px; padding: 10px 15px; font-weight: 700; color: #f5ebe0; }
#soft:hover { background: #4a3d2d; }
#danger { background: #4a2018; color: #ff6b6b; border: 2px solid #6b3020; border-radius: 12px; padding: 10px 14px; font-weight: 700; }
#danger:hover { background: #6b3020; }
#configCard { background: #2a1f14; border-radius: 24px; padding: 6px; border: 1px solid #3a2d20; }
#configTitle { font-family: Georgia, serif; font-size: 20px; font-weight: 900; color: #ffffff; }
#statusGood { color: #4ade80; font-weight: 800; font-size: 14px; }
#statusMuted { color: #a89a8b; font-size: 14px; }
QScrollBar:vertical { background: #1a0f08; width: 12px; border-radius: 6px; }
QScrollBar::handle:vertical { background: #ffd700; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #ffed4a; }
"""

# Estilo activo (inicialmente claro)
ESTILO = ESTILO_CLARO


class VentanaLoteria(QMainWindow):
    def __init__(self):
        super().__init__()
        self.conexion = conectar()
        crear_esquema(self.conexion)
        self.carta_actual: int | None = None
        self.reproductor: MediaPlayer | None = None
        self.archivo_audio: Path | None = None
        self.inicio_audio = 0.0
        self.idioma_audio: str | None = None
        self.lector: LectorRFID | None = None
        self.lecturas: queue.Queue = queue.Queue()
        self.reloj_audio = QTimer(self); self.reloj_audio.setInterval(100); self.reloj_audio.timeout.connect(self._vigilar_audio)
        self.reloj_lector = QTimer(self); self.reloj_lector.setInterval(120); self.reloj_lector.timeout.connect(self._revisar_lecturas); self.reloj_lector.start()
        
        # Variable para controlar el tema actual
        self.tema_oscuro = False
        
        # Diccionario para mapear UID a carta_id
        self.uid_a_carta = {}
        
        self.setWindowTitle("Lotería Mazahua")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(ESTILO)
        self._crear_ui()
        self.recargar_cartas()

    def etiqueta(self, texto: str, nombre="", padre=None) -> QLabel:
        label = QLabel(texto, padre)
        if nombre:
            label.setObjectName(nombre)
        label.setWordWrap(True)
        return label

    def boton(self, texto, funcion, nombre="action") -> QPushButton:
        boton = QPushButton(texto)
        boton.setObjectName(nombre)
        boton.clicked.connect(funcion)
        # Agregar efecto de sombra sutil
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(2, 2)
        boton.setGraphicsEffect(shadow)
        return boton

    def _crear_ui(self):
        raiz = QWidget(objectName="main")
        self.setCentralWidget(raiz)
        shell = QHBoxLayout(raiz); shell.setContentsMargins(0, 0, 0, 0); shell.setSpacing(0)
        shell.addWidget(self._crear_nav())
        self.pantallas = QStackedWidget(); shell.addWidget(self.pantallas, 1)
        self.pantallas.addWidget(self._pantalla_primaria())
        self.pantallas.addWidget(self._pantalla_edicion())
        self.pantallas.addWidget(self._pantalla_juego())
        self.pantallas.addWidget(self._pantalla_configuracion())

    def _crear_nav(self):
        nav = QFrame(objectName="nav")
        caja = QVBoxLayout(nav); caja.setContentsMargins(22, 30, 20, 26); caja.setSpacing(8)
        caja.addWidget(self.etiqueta("PROYECTO INTEGRADOR", "brandMark"))
        caja.addWidget(self.etiqueta("Lotería\nMazahua", "brandTitle"))
        caja.addWidget(self.etiqueta("Aprende escuchando y jugando con las tarjetas.", "brandText"))
        caja.addSpacing(30); caja.addWidget(self.etiqueta("MODOS", "navLabel"))
        self.nav_botones = []
        for indice, texto in enumerate(("◉  Primaria", "✎  Media superior · Edición", "▣  Juego · Tarjetas", "⚙  Configuración")):
            b = self.boton(texto, lambda _=False, i=indice: self.cambiar_pantalla(i), "navButton")
            b.setCheckable(True); self.nav_botones.append(b); caja.addWidget(b)
        self.nav_botones[0].setChecked(True)
        
        # Botón de cambio de tema
        caja.addSpacing(24)
        self.boton_tema = self.boton("🌙 Tema oscuro", self.alternar_tema, "soft")
        self.boton_tema.setToolTip("Cambiar entre tema claro y oscuro")
        caja.addWidget(self.boton_tema)
        
        caja.addStretch(); caja.addWidget(self.etiqueta(RUTA_BD.name, "navFoot"))
        return nav

    def cabecera(self, modo, titulo, descripcion):
        cont = QWidget(); caja = QVBoxLayout(cont); caja.setContentsMargins(36, 28, 36, 10); caja.setSpacing(4)
        caja.addWidget(self.etiqueta(modo.upper(), "eyebrow")); caja.addWidget(self.etiqueta(titulo, "title")); caja.addWidget(self.etiqueta(descripcion, "sub"))
        return cont

    def _pantalla_primaria(self):
        pagina = QWidget(); caja = QVBoxLayout(pagina); caja.setContentsMargins(0, 0, 0, 24); caja.setSpacing(10)
        self.titulo_primaria = self.etiqueta("Arrastra las cartas para reordenarlas", "title")
        caja.addWidget(self.cabecera("Modo Primaria", "Aprende jugando", "Arrastra las cartas · Haz clic para ver grande · Escucha los audios"))
        
        # Área principal con lista de cartas arrastrables
        self.lista_primaria = QListWidget(objectName="list")
        self.lista_primaria.setViewMode(QListWidget.IconMode)
        self.lista_primaria.setIconSize(QSize(180, 180))
        self.lista_primaria.setGridSize(QSize(200, 220))
        self.lista_primaria.setResizeMode(QListWidget.Adjust)
        self.lista_primaria.setMovement(QListWidget.Snap)  # Permite reordenar con drag & drop
        self.lista_primaria.setDragDropMode(QAbstractItemView.InternalMove)
        self.lista_primaria.setDefaultDropAction(Qt.MoveAction)
        self.lista_primaria.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista_primaria.setSpacing(12)
        self.lista_primaria.itemClicked.connect(self._seleccionar_carta_primaria)
        caja.addWidget(self.lista_primaria, 1)
        
        # Panel lateral con vista previa y audio
        lateral = QVBoxLayout(); lateral.setSpacing(14)
        
        self.previa_primaria = QLabel("Selecciona una carta", objectName="preview")
        self.previa_primaria.setAlignment(Qt.AlignCenter)
        self.previa_primaria.setMinimumSize(300, 300)
        self.previa_primaria.setMaximumSize(380, 380)
        self.previa_primaria.setScaledContents(False)
        
        # Sombra para la vista previa
        shadow_previa = QGraphicsDropShadowEffect()
        shadow_previa.setBlurRadius(20)
        shadow_previa.setColor(QColor(255, 215, 0, 60))
        shadow_previa.setOffset(4, 4)
        self.previa_primaria.setGraphicsEffect(shadow_previa)
        
        lateral.addWidget(self.previa_primaria)
        
        # Mostrar UID de la carta seleccionada
        self.uid_label = QLabel("UID: —", objectName="sub")
        self.uid_label.setAlignment(Qt.AlignCenter)
        self.uid_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #8b6f47;")
        lateral.addWidget(self.uid_label)
        
        voces = QVBoxLayout(); voces.setSpacing(12)
        self.voces = {}
        self.botones_audio_primaria = {}  # NUEVO: botones de audio para primaria
        colores = {"español": "#e67e22", "mazahua": "#27ae60", "inglés": "#2980b9"}
        for num, idioma in enumerate(IDIOMAS, 1):
            tarjeta = QFrame(objectName="wordCard"); fila = QHBoxLayout(tarjeta); fila.setContentsMargins(18, 16, 18, 16)
            
            # Sombra para las tarjetas de idioma
            shadow_tarjeta = QGraphicsDropShadowEffect()
            shadow_tarjeta.setBlurRadius(10)
            shadow_tarjeta.setColor(QColor(0, 0, 0, 20))
            shadow_tarjeta.setOffset(2, 2)
            tarjeta.setGraphicsEffect(shadow_tarjeta)
            
            n = self.etiqueta(str(num)); n.setAlignment(Qt.AlignCenter); n.setFixedSize(38, 38); n.setStyleSheet(f"background:{colores[idioma]}; color:white; border-radius:12px; font-weight:800; font-size: 16px;"); fila.addWidget(n)
            texto = QVBoxLayout(); idioma_label = self.etiqueta(idioma.upper(), "lang"); idioma_label.setStyleSheet(f"color:{colores[idioma]};"); texto.addWidget(idioma_label)
            palabra = self.etiqueta("—", "word"); texto.addWidget(palabra); fila.addLayout(texto, 1)
            
            # Botón de reproducción para primaria
            play = self.boton("▶", lambda _=False, i=idioma: self.reproducir_desde_primaria(i), "play")
            play.setStyleSheet(f"#play{{background:{colores[idioma]};}}")
            play.setEnabled(False)  # Se habilita cuando hay carta seleccionada con audio
            fila.addWidget(play)
            self.botones_audio_primaria[idioma] = play
            
            voces.addWidget(tarjeta); self.voces[idioma] = palabra
        voces.addStretch()
        lateral.addLayout(voces)
        
        player = QFrame(objectName="player"); fila_player = QHBoxLayout(player); fila_player.setContentsMargins(20, 14, 20, 14)
        
        # Sombra para el reproductor
        shadow_player = QGraphicsDropShadowEffect()
        shadow_player.setBlurRadius(12)
        shadow_player.setColor(QColor(0, 0, 0, 25))
        shadow_player.setOffset(2, 2)
        player.setGraphicsEffect(shadow_player)
        
        self.estado_audio = self.etiqueta("●  Selecciona una carta para escuchar", "statusMuted"); fila_player.addWidget(self.estado_audio, 1)
        self.boton_detener = self.boton("■ Detener", self.detener_audio, "soft"); self.boton_detener.setEnabled(False); fila_player.addWidget(self.boton_detener)
        lateral.addWidget(player)
        
        # Layout horizontal: lista a la izquierda, panel lateral a la derecha
        cuerpo = QHBoxLayout(); cuerpo.setContentsMargins(36, 0, 36, 0); cuerpo.setSpacing(28)
        cuerpo.addWidget(self.lista_primaria, 3)
        cuerpo.addLayout(lateral, 1)
        caja.addLayout(cuerpo, 1)
        
        return pagina

    def _pantalla_edicion(self):
        pagina = QWidget(); caja = QVBoxLayout(pagina); caja.setContentsMargins(0, 0, 0, 24); caja.setSpacing(8)
        caja.addWidget(self.cabecera("Media superior · Edición", "Editar carta", "Los campos se cargan desde SQLite y se guardan directamente en la base de datos."))
        cuerpo = QHBoxLayout(); cuerpo.setContentsMargins(36, 0, 36, 0); cuerpo.setSpacing(24); caja.addLayout(cuerpo, 1)
        izquierda = QVBoxLayout(); self.busqueda = QLineEdit(); self.busqueda.setObjectName("search"); self.busqueda.setPlaceholderText("Buscar carta..."); self.busqueda.textChanged.connect(self.filtrar); izquierda.addWidget(self.busqueda)
        self.lista = QListWidget(objectName="list"); self.lista.currentItemChanged.connect(self.seleccionar_lista); izquierda.addWidget(self.lista, 1)
        izquierda.addWidget(self.boton("+ Nueva carta", self.nueva_carta)); cuerpo.addLayout(izquierda, 1)
        editor = QFrame(objectName="editor"); ed = QVBoxLayout(editor); ed.setContentsMargins(28, 26, 28, 26); ed.setSpacing(16); cuerpo.addWidget(editor, 3)
        self.imagen_editor = QLabel("Sin imagen", objectName="preview"); self.imagen_editor.setAlignment(Qt.AlignCenter); self.imagen_editor.setFixedHeight(180); ed.addWidget(self.imagen_editor)
        ed.addWidget(self.boton("Cambiar imagen…", lambda: self.cargar("imagen"), "soft"))
        self.campos = {}
        self.botones_audio_edicion = {}
        colores = {"español": "#e67e22", "mazahua": "#27ae60", "inglés": "#2980b9"}
        for idioma in IDIOMAS:
            fila = QHBoxLayout(); etiqueta = self.etiqueta(idioma.capitalize()); etiqueta.setFixedWidth(100); fila.addWidget(etiqueta)
            entrada = QLineEdit(objectName="field"); entrada.editingFinished.connect(self.guardar); fila.addWidget(entrada, 1)
            fila.addWidget(self.boton("Cargar audio", lambda _=False, i=idioma: self.cargar(i), "soft"))
            # Botón de reproducción de audio - AHORA FUNCIONAL EN EDICIÓN
            play = self.boton("▶", lambda _=False, i=idioma: self.reproducir(i), "play")
            play.setStyleSheet(f"#play{{background:{colores[idioma]};}}")
            play.setEnabled(False)  # Se habilita cuando hay audio
            fila.addWidget(play)
            self.botones_audio_edicion[idioma] = play
            ed.addLayout(fila); self.campos[idioma] = entrada
        
        # Mostrar UID en edición
        self.uid_edicion_label = QLabel("UID RFID: No asignado", objectName="sub")
        self.uid_edicion_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #8b6f47; padding: 8px; background: #fffef5; border-radius: 8px;")
        ed.addWidget(self.uid_edicion_label)
        
        acciones = QHBoxLayout(); acciones.addWidget(self.boton("💾 Guardar cambios", self.guardar)); acciones.addWidget(self.boton("🎙 Grabar tarjeta RFID", self.aviso_rfid, "soft")); acciones.addStretch(); acciones.addWidget(self.boton("Eliminar", self.eliminar, "danger")); ed.addLayout(acciones)
        return pagina

    def _pantalla_juego(self):
        pagina = QWidget(); caja = QVBoxLayout(pagina); caja.setContentsMargins(0, 0, 40, 30); caja.addWidget(self.cabecera("Modo Juego", "Tarjetas RFID", "Acerca una tarjeta al lector")); caja.addStretch()
        self.juego = QLabel("Acerca una tarjeta", objectName="preview"); self.juego.setAlignment(Qt.AlignCenter); self.juego.setMinimumSize(360, 360); self.juego.setMaximumSize(470, 520); caja.addWidget(self.juego, 0, Qt.AlignHCenter)
        
        # Mostrar UID en modo juego
        self.uid_juego_label = QLabel("UID: Esperando lectura...", objectName="sub")
        self.uid_juego_label.setAlignment(Qt.AlignCenter)
        self.uid_juego_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #8b6f47; margin-top: 10px;")
        caja.addWidget(self.uid_juego_label)
        
        caja.addStretch()
        return pagina

    def _tarjeta_configuracion(self, titulo: str, descripcion: str) -> tuple[QFrame, QVBoxLayout]:
        tarjeta = QFrame(objectName="configCard")
        caja = QVBoxLayout(tarjeta); caja.setContentsMargins(24, 20, 24, 20); caja.setSpacing(8)
        caja.addWidget(self.etiqueta(titulo, "configTitle")); caja.addWidget(self.etiqueta(descripcion, "sub"))
        return tarjeta, caja

    def _pantalla_configuracion(self):
        pagina = QWidget(); caja = QVBoxLayout(pagina); caja.setContentsMargins(0, 0, 0, 26); caja.setSpacing(12)
        caja.addWidget(self.cabecera("Sistema", "Configuración", "Recursos, base de datos y conexión del lector RFID."))
        cuerpo = QVBoxLayout(); cuerpo.setContentsMargins(36, 0, 36, 0); cuerpo.setSpacing(16); caja.addLayout(cuerpo, 1)
        recursos, fila = self._tarjeta_configuracion("Recursos multimedia", "Importa o actualiza imágenes y audios dentro de SQLite.")
        acciones = QHBoxLayout(); acciones.addWidget(self.boton("⟳ Importar recursos", self.importar_recursos, "soft")); acciones.addWidget(self.boton("🇺🇸 Importar audios EN", self.importar_ingles, "soft")); acciones.addStretch(); fila.addLayout(acciones); cuerpo.addWidget(recursos)
        lector, fila = self._tarjeta_configuracion("Lector RFID", "Conecta el ESP32 para leer tarjetas en el modo Juego.")
        fila_lector = QHBoxLayout(); self.estado_lector = self.etiqueta("● Desconectado", "statusMuted"); fila_lector.addWidget(self.estado_lector, 1); self.boton_lector = self.boton("◉ Conectar lector", self.alternar_lector); fila_lector.addWidget(self.boton_lector); fila.addLayout(fila_lector); cuerpo.addWidget(lector)
        base, fila = self._tarjeta_configuracion("Base de datos", RUTA_BD.name)
        self.estado_bd = self.etiqueta("", "statusMuted"); fila.addWidget(self.estado_bd); cuerpo.addWidget(base)
        cuerpo.addStretch()
        return pagina

    def cambiar_pantalla(self, indice):
        self.pantallas.setCurrentIndex(indice)
        for i, boton in enumerate(self.nav_botones): boton.setChecked(i == indice)

    def alternar_tema(self):
        """Alterna entre tema claro y oscuro con animación"""
        self.tema_oscuro = not self.tema_oscuro
        
        # Animación de transición
        animacion = QPropertyAnimation(self, b"windowOpacity")
        animacion.setDuration(200)
        animacion.setStartValue(1.0)
        animacion.setEndValue(0.7)
        animacion.setEasingCurve(QEasingCurve.InOutQuad)
        
        def cambiar_estilo():
            if self.tema_oscuro:
                self.setStyleSheet(ESTILO_OSCURO)
                self.boton_tema.setText("☀️ Tema claro")
            else:
                self.setStyleSheet(ESTILO_CLARO)
                self.boton_tema.setText("🌙 Tema oscuro")
            # Restaurar opacidad
            animacion2 = QPropertyAnimation(self, b"windowOpacity")
            animacion2.setDuration(200)
            animacion2.setStartValue(0.7)
            animacion2.setEndValue(1.0)
            animacion2.setEasingCurve(QEasingCurve.InOutQuad)
            animacion2.start()
        
        animacion.finished.connect(cambiar_estilo)
        animacion.start()

    def recargar_cartas(self):
        self.filas = [dict(fila) for fila in resumen(self.conexion)]
        self.filtrar()
        self._actualizar_lista_primaria()
        
        # Actualizar mapeo UID a carta
        self._actualizar_mapeo_uid()
        
        if hasattr(self, "estado_bd"):
            medios = self.conexion.execute("SELECT count(*) FROM medio").fetchone()[0]
            self.estado_bd.setText(f"{len(self.filas)} cartas · {medios} recursos multimedia · SQLite sincronizada")

    def _actualizar_mapeo_uid(self):
        """Actualiza el diccionario que mapea UID a carta_id"""
        self.uid_a_carta.clear()
        cursor = self.conexion.execute("SELECT id, uid FROM cartas WHERE uid IS NOT NULL")
        for row in cursor:
            self.uid_a_carta[row['uid']] = row['id']

    def filtrar(self):
        texto = self.busqueda.text().casefold() if hasattr(self, "busqueda") else ""
        self.lista.blockSignals(True); self.lista.clear()
        for fila in self.filas:
            if texto and texto not in " ".join(str(fila[c] or "") for c in ("nombre", "mazahua", "ingles")).casefold(): continue
            item = QListWidgetItem(f"{fila['nombre'].capitalize()}\n{fila['mazahua'] or '—'} · {fila['ingles'] or '—'}"); item.setData(Qt.UserRole, fila["id"]); self.lista.addItem(item)
        self.lista.blockSignals(False)
        if self.lista.count(): self.lista.setCurrentRow(0)

    def _actualizar_lista_primaria(self):
        """Actualiza la lista de cartas en modo primaria con iconos arrastrables."""
        if not hasattr(self, 'lista_primaria'):
            return
        self.lista_primaria.blockSignals(True)
        self.lista_primaria.clear()
        for fila in self.filas:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, fila["id"])
            item.setText(fila["nombre"].capitalize())
            
            # Mostrar UID en el tooltip si existe
            uid_text = f"\nUID: {fila.get('uid', 'No asignado')}" if fila.get('uid') else ""
            item.setToolTip(f"{fila['mazahua'] or '—'} · {fila['ingles'] or '—'}{uid_text}")
            
            # Cargar imagen para el icono
            medio = obtener_medio(self.conexion, fila["id"], "imagen")
            if medio:
                pixmap = QPixmap()
                pixmap.loadFromData(medio["contenido"])
                # Escalar manteniendo aspecto
                pixmap = pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                item.setIcon(QIcon(pixmap))
            else:
                # Placeholder si no hay imagen
                pixmap = QPixmap(180, 180)
                pixmap.fill(QColor(245, 235, 224))
                painter = QPainter(pixmap)
                painter.setPen(QColor(139, 111, 71))
                painter.setFont(painter.font())
                painter.drawText(pixmap.rect(), Qt.AlignCenter, "Sin imagen")
                painter.end()
                item.setIcon(QIcon(pixmap))
            
            self.lista_primaria.addItem(item)
        self.lista_primaria.blockSignals(False)

    def _seleccionar_carta_primaria(self, item):
        """Maneja la selección de una carta en modo primaria."""
        carta_id = item.data(Qt.UserRole)
        if carta_id is None:
            return
        
        # CORRECCIÓN: Guardar la carta actual para reproducción de audio
        self.carta_actual = carta_id
        
        carta = obtener_carta(self.conexion, carta_id)
        if not carta:
            return
        
        # Actualizar vista previa
        self._poner_imagen(carta["id"])
        
        # Actualizar textos de idiomas
        valores = {"español": carta["nombre"], "mazahua": carta["mazahua"], "inglés": carta["ingles"]}
        for idioma, valor in valores.items():
            if idioma in self.voces:
                self.voces[idioma].setText(valor or "—")
        
        # Actualizar UID mostrado
        uid = carta.get('uid', 'No asignado')
        if hasattr(self, 'uid_label'):
            self.uid_label.setText(f"UID: {uid}" if uid != 'No asignado' else "UID: No asignado")
        
        # Habilitar/deshabilitar botones de audio según disponibilidad
        for idioma in IDIOMAS:
            medio = obtener_medio(self.conexion, carta_id, idioma)
            if idioma in self.botones_audio_primaria:
                self.botones_audio_primaria[idioma].setEnabled(medio is not None)

    def reproducir_desde_primaria(self, idioma):
        """Reproduce audio desde la pantalla primaria usando la carta seleccionada."""
        if not self.carta_actual:
            QMessageBox.information(self, "Audio", "Primero selecciona una carta.")
            return
        # Usar la misma función reproducir pero asegurando que carta_actual esté set
        self.reproducir(idioma)

    def seleccionar_lista(self, actual, _anterior=None):
        if not actual: return
        self.carta_actual = actual.data(Qt.UserRole); carta = obtener_carta(self.conexion, self.carta_actual)
        valores = {"español": carta["nombre"], "mazahua": carta["mazahua"], "inglés": carta["ingles"]}
        for idioma, valor in valores.items(): 
            self.campos[idioma].setText(valor or "")
            self.voces[idioma].setText(valor or "—")
            # Verificar si hay audio para habilitar botón de reproducción
            if hasattr(self, 'botones_audio_edicion') and idioma in self.botones_audio_edicion:
                medio = obtener_medio(self.conexion, self.carta_actual, idioma)
                self.botones_audio_edicion[idioma].setEnabled(medio is not None)
        self._poner_imagen(carta["id"])
        
        # Actualizar UID en edición
        uid = carta.get('uid', 'No asignado')
        if hasattr(self, 'uid_edicion_label'):
            self.uid_edicion_label.setText(f"UID RFID: {uid}" if uid != 'No asignado' else "UID RFID: No asignado")

    def _poner_imagen(self, carta_id):
        medio = obtener_medio(self.conexion, carta_id, "imagen")
        destino = [self.imagen_editor, self.previa_primaria]
        if not medio:
            for etiqueta in destino: 
                etiqueta.setPixmap(QPixmap())
                etiqueta.setText("Esta carta no tiene imagen")
            return
        pixmap = QPixmap(); pixmap.loadFromData(medio["contenido"])
        for etiqueta in destino:
            etiqueta.setText("")
            etiqueta.setPixmap(pixmap.scaled(etiqueta.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def nueva_carta(self):
        nombre = self.busqueda.text().strip()
        if not nombre:
            QMessageBox.information(self, "Nueva carta", "Escribe la palabra en el buscador y pulsa otra vez Nueva carta."); return
        try: carta_id = crear_carta(self.conexion, nombre)
        except ValueError as error: QMessageBox.warning(self, "Nueva carta", str(error)); return
        self.busqueda.clear(); self.recargar_cartas()
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.UserRole) == carta_id: self.lista.setCurrentRow(i); break

    def guardar(self):
        if not self.carta_actual: return
        try: guardar_textos(self.conexion, self.carta_actual, *(self.campos[i].text() for i in IDIOMAS))
        except ValueError as error: QMessageBox.warning(self, "No se pudo guardar", str(error)); return
        self.recargar_cartas(); self._seleccionar_id(self.carta_actual)

    def _seleccionar_id(self, carta_id):
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.UserRole) == carta_id: self.lista.setCurrentRow(i); break
        # Actualizar botones de audio en edición
        if hasattr(self, 'botones_audio_edicion'):
            for idioma in IDIOMAS:
                medio = obtener_medio(self.conexion, carta_id, idioma)
                self.botones_audio_edicion[idioma].setEnabled(medio is not None)
        
        # Actualizar UID en edición
        carta = obtener_carta(self.conexion, carta_id)
        if carta and hasattr(self, 'uid_edicion_label'):
            uid = carta.get('uid', 'No asignado')
            self.uid_edicion_label.setText(f"UID RFID: {uid}" if uid != 'No asignado' else "UID RFID: No asignado")

    def cargar(self, tipo):
        if not self.carta_actual: return
        filtros = "Imágenes (*.png *.jpg *.jpeg *.webp);;Todos (*.*)" if tipo == "imagen" else "Audio (*.mp3 *.wav *.ogg *.m4a *.mp4);;Todos (*.*)"
        ruta, _ = QFileDialog.getOpenFileName(self, "Selecciona un archivo", str(Path.cwd()), filtros)
        if not ruta: return
        try: cargar_medio(self.conexion, self.carta_actual, tipo, ruta)
        except ValueError as error: QMessageBox.warning(self, "Archivo no válido", str(error)); return
        if tipo == "imagen":
            self._poner_imagen(self.carta_actual)
        else:
            # Habilitar botón de reproducción para este idioma
            if hasattr(self, 'botones_audio_edicion') and tipo in self.botones_audio_edicion:
                self.botones_audio_edicion[tipo].setEnabled(True)
        self.recargar_cartas(); self._seleccionar_id(self.carta_actual)

    def eliminar(self):
        if not self.carta_actual or QMessageBox.question(self, "Eliminar carta", "¿Eliminar esta carta y sus recursos?") != QMessageBox.Yes: return
        eliminar_carta(self.conexion, self.carta_actual); self.carta_actual = None; self.recargar_cartas()

    def reproducir(self, idioma):
        """Reproduce el BLOB guardado en SQLite con el mismo motor interno."""
        if not self.carta_actual:
            QMessageBox.information(self, "Audio", "Primero selecciona una carta.")
            return
        medio = obtener_medio(self.conexion, self.carta_actual, idioma)
        if not medio:
            QMessageBox.information(self, "Audio", f"Esta carta aún no tiene audio en {idioma}.")
            return
        self.detener_audio()
        carpeta = Path(tempfile.gettempdir()) / "loteria_mazahua_audio"
        carpeta.mkdir(exist_ok=True)
        self.archivo_audio = carpeta / f"{uuid4().hex}{medio['extension']}"
        self.archivo_audio.write_bytes(medio["contenido"])
        try:
            self.reproductor = MediaPlayer(str(self.archivo_audio), ff_opts={"vn": True, "loop": 0})
            self.reproductor.set_pause(False)
            self.inicio_audio = time.monotonic()
            self.idioma_audio = idioma
            self.estado_audio.setObjectName("statusGood")
            self.estado_audio.setText(f"● Reproduciendo {idioma.capitalize()} · pulsa Detener para cancelar")
            self.estado_audio.style().unpolish(self.estado_audio); self.estado_audio.style().polish(self.estado_audio)
            self.boton_detener.setEnabled(True)
            self.reloj_audio.start()
        except Exception as error:
            self.detener_audio()
            QMessageBox.warning(self, "No se pudo reproducir", str(error))

    def _vigilar_audio(self):
        """Detecta el EOF y libera el motor/archivo temporal al terminar."""
        if not self.reproductor:
            self.reloj_audio.stop()
            return
        try:
            _frame, estado = self.reproductor.get_frame()
            duracion = float(self.reproductor.get_metadata().get("duration") or 0)
            terminado = estado == "eof" or (duracion > 0 and time.monotonic() - self.inicio_audio >= duracion + .2)
            if terminado:
                self.detener_audio(finalizo=True)
        except Exception:
            self.detener_audio(finalizo=True)

    def detener_audio(self, finalizo: bool = False):
        self.reloj_audio.stop()
        if self.reproductor:
            self.reproductor.close_player()
            self.reproductor = None
        if self.archivo_audio:
            try:
                self.archivo_audio.unlink(missing_ok=True)
            except OSError:
                pass
            self.archivo_audio = None
        self.idioma_audio = None
        if hasattr(self, "estado_audio"):
            self.estado_audio.setObjectName("statusMuted")
            self.estado_audio.setText("● Audio terminado" if finalizo else "● Selecciona una carta para escuchar")
            self.estado_audio.style().unpolish(self.estado_audio); self.estado_audio.style().polish(self.estado_audio)
        if hasattr(self, "boton_detener"):
            self.boton_detener.setEnabled(False)

    def importar_recursos(self):
        try:
            totales = importar_archivos(self.conexion)
        except Exception as error:
            QMessageBox.warning(self, "No se pudieron importar recursos", str(error)); return
        self.recargar_cartas()
        QMessageBox.information(self, "Recursos actualizados", " · ".join(f"{cantidad} {tipo}" for tipo, cantidad in totales.items()))

    def importar_ingles(self):
        try:
            total = importar_audios_ingles(self.conexion)
        except Exception as error:
            QMessageBox.warning(self, "No se pudieron importar los audios", str(error)); return
        self.recargar_cartas()
        QMessageBox.information(self, "Audios en inglés", f"Se importaron o actualizaron {total} audios.")

    def alternar_lector(self):
        if self.lector:
            self.lector.detener(); self.lector = None
            self.estado_lector.setObjectName("statusMuted"); self.estado_lector.setText("● Desconectado")
            self.boton_lector.setText("◉ Conectar lector")
            return
        puertos = listar_puertos()
        if not puertos:
            QMessageBox.information(self, "Lector RFID", "No se detectó ningún puerto serie. Conecta el ESP32 por USB.")
            return
        puerto = puertos[0]
        self.lector = LectorRFID(
            puerto, lambda lectura: self.lecturas.put({"lectura": lectura}),
            lambda error: self.lecturas.put({"error": error}),
            lambda es_error, mensaje: self.lecturas.put({"estado": mensaje, "es_error": es_error}),
        )
        self.lector.start()
        self.estado_lector.setObjectName("statusGood"); self.estado_lector.setText(f"● Conectando en {puerto}")
        self.estado_lector.style().unpolish(self.estado_lector); self.estado_lector.style().polish(self.estado_lector)
        self.boton_lector.setText("Desconectar lector")

    def _revisar_lecturas(self):
        while not self.lecturas.empty():
            evento = self.lecturas.get()
            if "error" in evento:
                self.lector = None
                if hasattr(self, "estado_lector"):
                    self.estado_lector.setText(evento["error"]); self.boton_lector.setText("◉ Conectar lector")
            elif "estado" in evento:
                if hasattr(self, "estado_lector"):
                    self.estado_lector.setText(evento["estado"])
            elif "lectura" in evento:
                lectura = evento["lectura"]
                carta, estado = emparejar_lectura(
                    self.conexion, lectura["uid"], [lectura["espanol"], lectura["mazahua"], lectura["ingles"]]
                )
                self.recargar_cartas()
                if carta:
                    self._seleccionar_id(carta["id"])
                    self.juego.setText(f"{carta['nombre'].capitalize()}\n\n{carta['mazahua'] or '—'} · {carta['ingles'] or '—'}\n\nRFID {lectura['uid']}")
                    self._poner_imagen(carta["id"])
                    
                    # Actualizar UID en modo juego
                    if hasattr(self, 'uid_juego_label'):
                        self.uid_juego_label.setText(f"UID: {lectura['uid']}")
                
                if hasattr(self, "estado_lector"):
                    self.estado_lector.setText(f"● Lectura {estado}: {lectura['uid']}")

    def aviso_rfid(self):
        """Graba la tarjeta RFID actual con los datos de la carta seleccionada."""
        if self.carta_actual is None:
            QMessageBox.warning(self, "RFID", "Primero selecciona una carta para grabar.")
            return

        carta = obtener_carta(self.conexion, self.carta_actual)
        if not carta:
            QMessageBox.warning(self, "RFID", "No se encontró la carta seleccionada.")
            return

        # Verificar si hay lector conectado
        if not self.lector:
            respuesta = QMessageBox.question(
                self, "RFID - Lector no conectado",
                "No hay lector RFID conectado. ¿Quieres conectar uno ahora?",
                QMessageBox.Yes | QMessageBox.No
            )
            if respuesta == QMessageBox.Yes:
                self.alternar_lector()
                # Esperar un poco a que se conecte
                QTimer.singleShot(1500, lambda: self._grabar_rfid_carta(carta))
            return

        self._grabar_rfid_carta(carta)

    def _grabar_rfid_carta(self, carta):
        """Envía el comando de grabación al ESP32 y espera la respuesta."""
        if not self.lector:
            QMessageBox.warning(self, "RFID", "El lector no está conectado.")
            return

        # Preparar textos para grabar (máx 16 bytes cada uno)
        espanol = carta["nombre"] or ""
        mazahua = carta["mazahua"] or ""
        ingles = carta["ingles"] or ""

        # Enviar comando de grabación
        comando = comando_grabar(espanol, mazahua, ingles)
        if not self.lector.enviar(comando):
            QMessageBox.warning(self, "RFID", "No se pudo enviar el comando al lector.")
            return

        # Mostrar diálogo de espera
        self._dialogo_grabacion = QMessageBox(self)
        self._dialogo_grabacion.setWindowTitle("Grabando tarjeta RFID")
        self._dialogo_grabacion.setText("Acerca una tarjeta en blanco al lector...\n\nEsperando respuesta del ESP32...")
        self._dialogo_grabacion.setStandardButtons(QMessageBox.Cancel)
        self._dialogo_grabacion.button(QMessageBox.Cancel).setText("Cancelar")
        self._dialogo_grabacion.setModal(True)
        
        # Timer para verificar la respuesta
        self._timer_grabacion = QTimer(self)
        self._timer_grabacion.setInterval(200)
        self._timer_grabacion.timeout.connect(lambda: self._verificar_grabacion(carta))
        self._timer_grabacion.start()
        
        self._dialogo_grabacion.show()

    def _verificar_grabacion(self, carta):
        """Verifica si hay respuesta de grabación en la cola."""
        while not self.lecturas.empty():
            evento = self.lecturas.get()
            if "grabacion" in evento:
                self._timer_grabacion.stop()
                if hasattr(self, '_dialogo_grabacion'):
                    self._dialogo_grabacion.close()
                
                grabacion = evento["grabacion"]
                if grabacion == "ok":
                    uid = evento.get("uid", "desconocido")
                    # Reasignar UID en la base de datos
                    anterior = reasignar_uid(self.conexion, carta["id"], uid)
                    extra = f" (se quitó de «{anterior}»)" if anterior else ""
                    QMessageBox.information(
                        self, "RFID - Grabación exitosa",
                        f"Tarjeta {uid} grabada y asignada a «{carta['nombre']}»{extra}.\nRetira la tarjeta del lector."
                    )
                    self.recargar_cartas()
                elif grabacion == "error":
                    motivo = evento.get("motivo", "Error desconocido")
                    QMessageBox.warning(self, "RFID - Error", f"No se pudo grabar: {motivo}")
                elif grabacion == "cancelado":
                    QMessageBox.information(self, "RFID", "Grabación cancelada.")
                return
            elif "error" in evento:
                self._timer_grabacion.stop()
                if hasattr(self, '_dialogo_grabacion'):
                    self._dialogo_grabacion.close()
                QMessageBox.warning(self, "RFID - Error", f"Error del lector: {evento['error']}")
                return

    def closeEvent(self, event):
        self.detener_audio()
        if self.lector:
            self.lector.detener()
        self.conexion.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaLoteria(); ventana.show()
    sys.exit(app.exec())