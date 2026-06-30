"""
Volume Controller — Control de volumen por gestos de mano.

Interfaz profesional con:
- Control de volumen por pinch (pulgar + índice)
- Detección de swipe horizontal para mostrar animación
- Animaciones suaves a 60fps
- Diseño oscuro minimalista
"""

import tkinter as tk
from tkinter import font as tkfont
import cv2
import mediapipe as mp
import math
import subprocess
import shutil
import threading
import time
import io
from PIL import Image, ImageTk, ImageDraw
from pathlib import Path
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

# ═══════════════════════════════════════════════════════════════════
#  Rutas y configuración
# ═══════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent
MODEL_PATH = str(BASE_DIR / "assets" / "hand_landmarker.task")
GIF_PATH = str(BASE_DIR / "assets" / "scuba-scuba-cat.gif")
CAM_WIDTH = 640
CAM_HEIGHT = 480
CAMERA_INDEX = 0

# Wave detection (agitar mano)
WAVE_DIRECTION_THRESHOLD = 15   # píxeles mínimos para cambio de dirección
WAVE_MIN_CHANGES = 2            # cambios de dirección mínimos
WAVE_FRAMES_WINDOW = 12         # ventana de frames para detectar wave
WAVE_COOLDOWN = 5               # frames de espera post-wave (~160ms)

# ═══════════════════════════════════════════════════════════════════
#  Paleta de colores
# ═══════════════════════════════════════════════════════════════════

C = {
    "bg":         "#0a0e17",
    "surface":    "#111827",
    "card":       "#1a2235",
    "border":     "#2a3450",
    "accent":     "#6366f1",
    "accent2":    "#818cf8",
    "green":      "#10b981",
    "green2":     "#34d399",
    "red":        "#ef4444",
    "orange":     "#f59e0b",
    "pink":       "#ec4899",
    "cyan":       "#22d3ee",
    "text":       "#f1f5f9",
    "text2":      "#94a3b8",
    "text3":      "#475569",
    "bar_bg":     "#1e293b",
}


# ═══════════════════════════════════════════════════════════════════
#  Audio del sistema
# ═══════════════════════════════════════════════════════════════════

def detect_audio_backend() -> str | None:
    if shutil.which("wpctl"):
        return "wpctl"
    if shutil.which("amixer"):
        return "amixer"
    return None

AUDIO_BACKEND = detect_audio_backend()

def set_volume(level: float) -> None:
    level = max(0.0, min(1.0, level))
    try:
        if AUDIO_BACKEND == "wpctl":
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif AUDIO_BACKEND == "amixer":
            subprocess.run(
                ["amixer", "sset", "Master", f"{int(level * 100)}%"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except FileNotFoundError:
        pass

def get_volume() -> float:
    try:
        if AUDIO_BACKEND == "wpctl":
            r = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True,
            )
            parts = r.stdout.strip().split()
            if len(parts) >= 3:
                return float(parts[2])
        elif AUDIO_BACKEND == "amixer":
            r = subprocess.run(
                ["amixer", "sget", "Master"], capture_output=True, text=True,
            )
            for line in r.stdout.splitlines():
                if "Playback" in line and "%" in line:
                    return int(line[line.index("[") + 1:line.index("%")]) / 100.0
    except Exception:
        pass
    return 0.5


# ═══════════════════════════════════════════════════════════════════
#  Utilidades
# ═══════════════════════════════════════════════════════════════════

def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    t = max(0.0, min(1.0, t))
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


# ═══════════════════════════════════════════════════════════════════
#  Ventana del GIF
# ═══════════════════════════════════════════════════════════════════

class GifWindow:
    """Ventana emergente que reproduce un GIF animado con fade-out."""

    def __init__(self, parent: tk.Tk, gif_path: str):
        self.win = tk.Toplevel(parent)
        self.win.title("")
        self.win.configure(bg="#000000")
        self.win.resizable(False, False)
        self.win.overrideredirect(True)
        self.win.attributes("-alpha", 1.0)

        self.frames = []
        self.current_frame = 0
        self.playing = True
        self._fading = False
        self._alpha = 1.0

        self._load_gif(gif_path)
        if not self.frames:
            self.win.destroy()
            return

        # Centrar sobre la ventana padre
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        gw = self.frames[0].width
        gh = self.frames[0].height
        x = px + (pw - gw) // 2
        y = py + (ph - gh) // 2
        self.win.geometry(f"{gw}x{gh}+{x}+{y}")

        self.label = tk.Label(self.win, bg="#000000", bd=0)
        self.label.pack()

        self.label.bind("<Button-1>", lambda e: self.close())
        self.win.bind("<Escape>", lambda e: self.close())

        self._animate()
        # Empezar fade-out a los 0.3 segundos
        self.win.after(300, self._start_fade)

    def _load_gif(self, path: str):
        """Carga todos los frames del GIF."""
        try:
            gif = Image.open(path)
            while True:
                frame = gif.copy().convert("RGBA")
                self.frames.append(frame)
                gif.seek(gif.tell() + 1)
        except EOFError:
            pass
        except Exception:
            pass

    def _animate(self):
        """Reproduce el GIF en loop."""
        if not self.playing or not self.frames:
            return
        frame = self.frames[self.current_frame]
        photo = ImageTk.PhotoImage(frame)
        self.label.config(image=photo)
        self.label._photo_ref = photo
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.win.after(50, self._animate)

    def _start_fade(self):
        """Inicia la animación de fade-out."""
        self._fading = True
        self._fade_step()

    def _fade_step(self):
        """Un paso de la animación de fade-out."""
        if not self.playing:
            return
        self._alpha -= 0.08
        if self._alpha <= 0:
            self.close()
            return
        self.win.attributes("-alpha", self._alpha)
        self.win.after(20, self._fade_step)  # ~400ms total

    def close(self):
        self.playing = False
        try:
            self.win.destroy()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
#  App principal
# ═══════════════════════════════════════════════════════════════════

class VolumeApp:
    """App de escritorio para control de volumen por gestos de mano."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Volume Controller")
        self.root.configure(bg=C["bg"])
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Estado de cámara
        self.running = False
        self.cap = None
        self.hand_landmarker = None
        self.current_volume = get_volume()
        self.display_volume = self.current_volume
        self.target_volume = self.current_volume
        self.frame_count = 0
        self._photo_ref = None

        # Wave detection
        self.wrist_history = []  # historial de posiciones X
        self.wave_cooldown = 0

        # Animación
        self._pulse = 0.0
        self._gesture_active = False
        self._gesture_color = C["text3"]

        # GIF window reference
        self._gif_win = None

        self._build_ui()
        self._center_window()
        self._start_animation_loop()

    # ──────────────────────────────────────────────────────────────
    #  UI profesional
    # ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Fuentes
        try:
            self.font_sm = tkfont.Font(family="Inter", size=10)
            self.font_md = tkfont.Font(family="Inter", size=12)
            self.font_lg = tkfont.Font(family="Inter", size=32, weight="bold")
            self.font_title = tkfont.Font(family="Inter", size=9, weight="bold")
        except Exception:
            self.font_sm = tkfont.Font(family="monospace", size=10)
            self.font_md = tkfont.Font(family="monospace", size=12)
            self.font_lg = tkfont.Font(family="monospace", size=32, weight="bold")
            self.font_title = tkfont.Font(family="monospace", size=9, weight="bold")

        # ── Layout ──
        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        # ── Panel cámara ──
        cam_card = tk.Frame(outer, bg=C["card"], bd=0, highlightthickness=0)
        cam_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Línea accent superior
        self.accent_bar = tk.Frame(cam_card, bg=C["accent"], height=3)
        self.accent_bar.pack(fill=tk.X)

        # Canvas de cámara
        cam_inner = tk.Frame(cam_card, bg=C["surface"])
        cam_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 2))

        self.canvas = tk.Canvas(
            cam_inner, bg=C["surface"], highlightthickness=0,
            width=CAM_WIDTH, height=CAM_HEIGHT,
        )
        self.canvas.pack(expand=True)

        self.placeholder_id = self.canvas.create_text(
            CAM_WIDTH // 2, CAM_HEIGHT // 2,
            text="▶  Iniciar cámara", fill=C["text3"],
            font=("monospace", 16),
        )

        # ── Panel controles ──
        right = tk.Frame(outer, bg=C["bg"], width=240)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(24, 0))
        right.pack_propagate(False)

        # Header con líneas decorativas
        header_frame = tk.Frame(right, bg=C["bg"])
        header_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(
            header_frame, text="VOLUME", bg=C["bg"], fg=C["text3"],
            font=self.font_title, anchor="w",
        ).pack(side=tk.LEFT)

        tk.Frame(
            header_frame, bg=C["border"], height=1,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0), pady=(6, 0))

        # ── Barra de volumen ──
        bar_frame = tk.Frame(right, bg=C["card"], bd=0, highlightthickness=0)
        bar_frame.pack(fill=tk.X, pady=(0, 20))

        bar_inner = tk.Frame(bar_frame, bg=C["card"])
        bar_inner.pack(padx=16, pady=16)

        self.bar_canvas = tk.Canvas(
            bar_inner, bg=C["card"], highlightthickness=0,
            width=48, height=280, bd=0,
        )
        self.bar_canvas.pack()

        # Fondo barra
        self.bar_canvas.create_rectangle(
            12, 8, 36, 272, outline=C["border"], width=1, fill=C["bar_bg"],
        )

        # Glow (detrás)
        self.bar_glow = self.bar_canvas.create_rectangle(
            10, 270, 38, 274, fill=C["green"], outline="", width=0,
        )
        self.bar_canvas.tag_lower(self.bar_glow)

        # Relleno
        self.bar_rect = self.bar_canvas.create_rectangle(
            14, 270, 34, 272, fill=C["green"], outline="", width=0,
        )

        # Ticks
        for i in range(10):
            y = 272 - int((i + 1) * 264 / 10)
            self.bar_canvas.create_line(
                8, y, 12, y, fill=C["border"], width=1,
            )

        # ── Porcentaje ──
        vol_frame = tk.Frame(right, bg=C["bg"])
        vol_frame.pack(fill=tk.X, pady=(0, 4))

        self.vol_label = tk.Label(
            vol_frame, text=f"{int(self.current_volume * 100)}%",
            bg=C["bg"], fg=C["green"], font=self.font_lg, anchor="w",
        )
        self.vol_label.pack(side=tk.LEFT)

        tk.Label(
            vol_frame, text="vol", bg=C["bg"], fg=C["text3"],
            font=self.font_sm, anchor="w",
        ).pack(side=tk.LEFT, padx=(8, 0), pady=(12, 0))

        # ── Indicador de gesto ──
        gest_frame = tk.Frame(right, bg=C["bg"])
        gest_frame.pack(fill=tk.X, pady=(0, 20))

        self.gesture_dot = tk.Canvas(
            gest_frame, bg=C["bg"], highlightthickness=0,
            width=12, height=12, bd=0,
        )
        self.gesture_dot.pack(side=tk.LEFT)
        self.gesture_dot.create_oval(1, 1, 11, 11, fill=C["text3"], outline="", tags="dot")

        self.gesture_label = tk.Label(
            gest_frame, text="Esperando mano", bg=C["bg"], fg=C["text3"],
            font=self.font_sm, anchor="w",
        )
        self.gesture_label.pack(side=tk.LEFT, padx=(8, 0))

        # Separador
        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X, pady=(0, 20))

        # ── Estado ──
        self.status_label = tk.Label(
            right, text="Listo", bg=C["bg"], fg=C["text2"],
            font=self.font_sm, anchor="w",
        )
        self.status_label.pack(fill=tk.X, pady=(0, 6))

        self.mode_label = tk.Label(
            right, text="Modo: —", bg=C["bg"], fg=C["text3"],
            font=self.font_sm, anchor="w",
        )
        self.mode_label.pack(fill=tk.X, pady=(0, 24))

        # ── Swipe info ──
        swipe_frame = tk.Frame(right, bg=C["bg"])
        swipe_frame.pack(fill=tk.X, pady=(0, 20))

        self.swipe_label = tk.Label(
            swipe_frame, text="↔  Agita la mano", bg=C["bg"], fg=C["text3"],
            font=self.font_sm, anchor="w",
        )
        self.swipe_label.pack(fill=tk.X)

        # Separador
        tk.Frame(right, bg=C["border"], height=1).pack(fill=tk.X, pady=(0, 20))

        # ── Botón ──
        self.btn_frame = tk.Frame(right, bg=C["bg"])
        self.btn_frame.pack(fill=tk.X)

        self.start_btn = tk.Label(
            self.btn_frame, text="▶  Iniciar Cámara",
            bg=C["accent"], fg="white", font=self.font_md,
            anchor="center", cursor="hand2", padx=20, pady=10,
        )
        self.start_btn.pack(fill=tk.X)
        self.start_btn.bind("<Button-1>", lambda e: self._toggle_camera())
        self.start_btn.bind("<Enter>", self._btn_enter)
        self.start_btn.bind("<Leave>", self._btn_leave)

        # Backend
        tk.Label(
            right, text=f"Backend: {AUDIO_BACKEND or '—'}", bg=C["bg"], fg=C["text3"],
            font=("monospace", 8), anchor="w",
        ).pack(fill=tk.X, pady=(12, 0))

    def _btn_enter(self, e):
        if not self.running:
            self.start_btn.config(bg=C["accent2"])

    def _btn_leave(self, e):
        if not self.running:
            self.start_btn.config(bg=C["accent"])

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

    # ──────────────────────────────────────────────────────────────
    #  Animación suave
    # ──────────────────────────────────────────────────────────────

    def _start_animation_loop(self):
        self._animate_step()
        self.root.after(16, self._start_animation_loop)

    def _animate_step(self):
        diff = self.target_volume - self.display_volume

        if abs(diff) > 0.003:
            self.display_volume += diff * 0.2
            self._render_bar(self.display_volume)
        elif abs(diff) > 0:
            self.display_volume = self.target_volume
            self._render_bar(self.display_volume)

        # Pulso del dot
        if self._gesture_active:
            self._pulse += 0.12
            p = (math.sin(self._pulse) + 1) / 2
            color = lerp_color(C["green"], C["green2"], p)
            self.gesture_dot.itemconfig("dot", fill=color)
        else:
            self._pulse = 0.0

    def _render_bar(self, vol: float):
        vol = max(0.0, min(1.0, vol))
        fill_h = max(2, int(vol * 264))
        y_top = 272 - fill_h

        if vol < 0.25:
            color = C["red"]
        elif vol < 0.5:
            color = C["orange"]
        elif vol < 0.75:
            color = C["green"]
        else:
            color = C["green2"]

        self.bar_canvas.coords(self.bar_rect, 14, y_top, 34, 272)
        self.bar_canvas.itemconfig(self.bar_rect, fill=color)
        self.bar_canvas.coords(self.bar_glow, 10, y_top - 2, 38, 274)
        self.bar_canvas.itemconfig(self.bar_glow, fill=color)

        pct = int(vol * 100)
        self.vol_label.config(text=f"{pct}%", fg=color)

    # ──────────────────────────────────────────────────────────────
    #  Cámara y detección
    # ──────────────────────────────────────────────────────────────

    def _init_model(self):
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
        )
        self.hand_landmarker = HandLandmarker.create_from_options(options)

    def _toggle_camera(self):
        if self.running:
            self._stop_camera()
        else:
            self._start_camera()

    def _start_camera(self):
        self.running = True
        self.start_btn.config(text="⏹  Detener", bg=C["red"])
        self.canvas.delete(self.placeholder_id)
        self.status_label.config(text="Iniciando...")
        threading.Thread(target=self._camera_loop, daemon=True).start()

    def _stop_camera(self):
        self.running = False
        self.start_btn.config(text="▶  Iniciar Cámara", bg=C["accent"])
        self.status_label.config(text="Detenido")
        self.mode_label.config(text="Modo: —", fg=C["text3"])
        self.gesture_label.config(text="Esperando mano", fg=C["text3"])
        self.gesture_dot.itemconfig("dot", fill=C["text3"])
        self.swipe_label.config(text="↔  Agita la mano", fg=C["text3"])
        self._gesture_active = False
        self.wave_cooldown = 0
        if self.cap:
            self.cap.release()
            self.cap = None
        self.canvas.delete("all")
        self.placeholder_id = self.canvas.create_text(
            CAM_WIDTH // 2, CAM_HEIGHT // 2,
            text="▶  Iniciar cámara", fill=C["text3"],
            font=("monospace", 16),
        )

    def _camera_loop(self):
        """Loop principal de cámara."""
        try:
            if self.hand_landmarker is None:
                self.root.after(0, lambda: self.status_label.config(
                    text="Cargando modelo...",
                ))
                self._init_model()

            self.cap = cv2.VideoCapture(CAMERA_INDEX)
            if not self.cap.isOpened():
                self.root.after(0, lambda: self.status_label.config(
                    text="Error: Sin cámara",
                ))
                self.running = False
                return

            self.root.after(0, lambda: self.status_label.config(
                text="Cámara activa",
            ))
            self.frame_count = 0

            while self.running:
                ret, frame = self.cap.read()
                if not ret:
                    break

                frame = cv2.flip(frame, 1)
                self.frame_count += 1

                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
                results = self.hand_landmarker.detect_for_video(
                    mp_image, int(time.time() * 1000),
                )

                mode_text = "Sin mano"
                gesture_active = False

                if results.hand_landmarks:
                    hand = results.hand_landmarks[0]
                    h, w, _ = frame.shape

                    thumb = hand[4]
                    index = hand[8]
                    wrist = hand[0]
                    tx, ty = int(thumb.x * w), int(thumb.y * h)
                    ix, iy = int(index.x * w), int(index.y * h)
                    wx = int(wrist.x * w)

                    margin = 0.85

                    def is_curled(tip, knuckle):
                        td = math.hypot(tip.x - wrist.x, tip.y - wrist.y)
                        kd = math.hypot(knuckle.x - wrist.x, knuckle.y - wrist.y)
                        return td < kd * margin

                    curled = (
                        is_curled(hand[12], hand[9])
                        and is_curled(hand[16], hand[13])
                        and is_curled(hand[20], hand[17])
                    )

                    # ── Detección de wave (agitar mano) ──
                    wave_detected = False
                    if self.wave_cooldown > 0:
                        self.wave_cooldown -= 1
                    else:
                        # Guardar posición X en historial
                        self.wrist_history.append(wx)
                        if len(self.wrist_history) > WAVE_FRAMES_WINDOW:
                            self.wrist_history.pop(0)

                        # Detectar cambios de dirección
                        if len(self.wrist_history) >= 3:
                            direction_changes = 0
                            for i in range(2, len(self.wrist_history)):
                                d1 = self.wrist_history[i-1] - self.wrist_history[i-2]
                                d2 = self.wrist_history[i] - self.wrist_history[i-1]
                                if d1 * d2 < 0 and abs(d2) > WAVE_DIRECTION_THRESHOLD // 3:
                                    direction_changes += 1
                            if direction_changes >= WAVE_MIN_CHANGES:
                                wave_detected = True
                                self.wave_cooldown = WAVE_COOLDOWN
                                self.wrist_history.clear()

                    if wave_detected and self._gif_win is None:
                        self.root.after(0, self._show_gif)

                    # ── Dibujar frame ──
                    cv2.circle(frame, (tx, ty), 10, (99, 102, 241), 2)
                    cv2.circle(frame, (ix, iy), 10, (99, 102, 241), 2)

                    if curled:
                        gesture_active = True
                        mode_text = "Volumen"
                        d = math.hypot(ix - tx, iy - ty)
                        vol = max(0.0, min(1.0, (d - 20) / 180))

                        if self.frame_count % 10 == 0:
                            set_volume(vol)
                            self.target_volume = vol
                            self.current_volume = vol

                        cv2.line(frame, (tx, ty), (ix, iy), (16, 185, 129), 3)
                        cv2.line(frame, (tx, ty), (ix, iy), (52, 211, 153), 1)
                    else:
                        mode_text = "Mano abierta"
                        cv2.line(frame, (tx, ty), (ix, iy), (99, 102, 241), 2)

                    # Wave visual feedback
                    if self.wave_cooldown > WAVE_COOLDOWN - 15:
                        cv2.putText(
                            frame, "WAVE!", (w // 2 - 70, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (34, 211, 238), 3,
                        )

                # ── Actualizar UI ──
                self._gesture_active = gesture_active
                m_text = mode_text
                g_color = C["green"] if gesture_active else C["text3"]
                g_label = (
                    "Gesto activo" if gesture_active
                    else ("Mano detectada" if results.hand_landmarks else "Esperando mano")
                )

                self.root.after(0, lambda mt=m_text, gc=g_color, gl=g_label: (
                    self.mode_label.config(
                        text=f"Modo: {mt}",
                        fg=C["green"] if mt == "Volumen" else C["text3"],
                    ),
                    self.gesture_dot.itemconfig("dot", fill=gc),
                    self.gesture_label.config(text=gl, fg=gc),
                    self.swipe_label.config(
                        text="↔  Wave detectado!" if self.wave_cooldown > WAVE_COOLDOWN - 20
                        else "↔  Agita la mano",
                        fg=C["cyan"] if self.wave_cooldown > WAVE_COOLDOWN - 20 else C["text3"],
                    ),
                ))

                # ── Renderizar ──
                _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                img = Image.open(io.BytesIO(buffer.tobytes()))

                cw = self.canvas.winfo_width()
                ch = self.canvas.winfo_height()
                if cw > 1 and ch > 1:
                    img = img.resize((cw, ch), Image.LANCZOS)

                photo = ImageTk.PhotoImage(img)
                self.root.after(0, lambda p=photo: self._draw_frame(p))

        except Exception as exc:
            error_msg = str(exc)
            self.root.after(0, lambda msg=error_msg:
                self.status_label.config(text=f"Error: {msg}"))
        finally:
            self.running = False
            if self.cap:
                self.cap.release()
                self.cap = None

    def _draw_frame(self, photo):
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        self._photo_ref = photo

    def _show_gif(self):
        """Abre ventana con el GIF animado."""
        if self._gif_win is not None:
            return
        self._gif_win = GifWindow(self.root, GIF_PATH)
        # Limpiar referencia cuando se cierra
        self.root.after(4000, self._cleanup_gif)

    def _cleanup_gif(self):
        self._gif_win = None

    # ──────────────────────────────────────────────────────────────
    #  Cierre
    # ──────────────────────────────────────────────────────────────

    def _on_close(self):
        self.running = False
        if self.cap:
            self.cap.release()
        if self.hand_landmarker:
            self.hand_landmarker.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = VolumeApp()
    app.run()
