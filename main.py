"""
Volume Controller — Control de volumen por gestos de mano.

Interfaz profesional con:
- Control de volumen por pinch (pulgar + indice)
- Deteccion de swipe horizontal para mostrar animacion
- Animaciones suaves a 60fps
- Diseno oscuro elegante
- Soporte para Linux (wpctl/amixer) y Windows (Core Audio API)
"""

import sys
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
from PIL import Image, ImageTk, ImageDraw, ImageFont
from pathlib import Path
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

# =====================================================================
#  Rutas y configuracion
# =====================================================================

BASE_DIR = Path(__file__).parent
MODEL_PATH = str(BASE_DIR / "assets" / "hand_landmarker.task")
GIF_PATH = str(BASE_DIR / "assets" / "scuba-scuba-cat.gif")
CAM_WIDTH = 640
CAM_HEIGHT = 480
CAMERA_INDEX = 0

# Wave detection (agitar mano rapido)
WAVE_DIRECTION_THRESHOLD = 12
WAVE_MIN_CHANGES = 2
WAVE_FRAMES_WINDOW = 20
WAVE_TIME_WINDOW = 0.8
WAVE_COOLDOWN = 3

# =====================================================================
#  Paleta de colores - Negro elegante
# =====================================================================

C = {
    "bg":         "#050505",
    "surface":    "#0a0a0a",
    "card":       "#111111",
    "card2":      "#161616",
    "border":     "#222222",
    "border2":    "#2a2a2a",
    "accent":     "#7c5cfc",
    "accent2":    "#9b7dff",
    "accent_dim": "#4a3a8a",
    "green":      "#00e676",
    "green2":     "#69f0ae",
    "red":        "#ff1744",
    "orange":     "#ff9100",
    "pink":       "#ff4081",
    "cyan":       "#00e5ff",
    "text":       "#e0e0e0",
    "text2":      "#888888",
    "text3":      "#444444",
    "bar_bg":     "#1a1a1a",
    "glow":       "#7c5cfc",
}


# =====================================================================
#  Audio del sistema (Linux + Windows)
# =====================================================================

def _detect_audio_backend_linux() -> str | None:
    if shutil.which("wpctl"):
        return "wpctl"
    if shutil.which("amixer"):
        return "amixer"
    return None


def _detect_audio_backend_windows() -> str | None:
    try:
        import ctypes
        from ctypes import wintypes
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)
        mmdeviceapi = ctypes.windll["mmdeviceapi.dll"]
        CLSID_MMDeviceEnumerator = '{BCDE0395-E52F-467C-8E3D-C4579291692E}'
        IID_IMMDeviceEnumerator = '{A95664D2-9614-4F35-A746-DE8DB63617E6}'
        IID_IAudioEndpointVolume = '{5CDF2C82-841E-4546-9722-0CF74078229A}'
        class IMMDeviceEnumerator(ctypes.Structure):
            pass
        pEnumerator = ctypes.POINTER(c_void_p)()
        hr = mmdeviceapi.CCoCreateInstance(
            ctypes.wintypes.GUID.from_string(CLSID_MMDeviceEnumerator),
            None, 1, ctypes.wintypes.GUID.from_string(IID_IMMDeviceEnumerator),
            ctypes.byref(pEnumerator),
        )
        if hr == 0:
            return "windows_core"
    except Exception:
        pass
    return None


AUDIO_BACKEND = None
if sys.platform == "win32":
    AUDIO_BACKEND = _detect_audio_backend_windows()
else:
    AUDIO_BACKEND = _detect_audio_backend_linux()

if AUDIO_BACKEND is None and sys.platform == "win32":
    AUDIO_BACKEND = "windows_powershell"


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
        elif AUDIO_BACKEND == "windows_core":
            import ctypes
            from ctypes import wintypes
            ole32 = ctypes.windll.ole32
            ole32.CoInitializeEx(None, 0)
            mmdeviceapi = ctypes.windll["mmdeviceapi.dll"]
            CLSID_MMDeviceEnumerator = '{BCDE0395-E52F-467C-8E3D-C4579291692E}'
            IID_IMMDeviceEnumerator = '{A95664D2-9614-4F35-A746-DE8DB63617E6}'
            IID_IAudioEndpointVolume = '{5CDF2C82-841E-4546-9722-0CF74078229A}'
            pEnumerator = ctypes.POINTER(c_void_p)()
            hr = mmdeviceapi.CCoCreateInstance(
                ctypes.wintypes.GUID.from_string(CLSID_MMDeviceEnumerator),
                None, 1, ctypes.wintypes.GUID.from_string(IID_IMMDeviceEnumerator),
                ctypes.byref(pEnumerator),
            )
            if hr == 0:
                pDevice = ctypes.POINTER(c_void_p)()
                hr = pEnumerator.GetDefaultAudioEndpoint(0, 1, ctypes.byref(pDevice))
                if hr == 0:
                    pVolume = ctypes.POINTER(c_void_p)()
                    hr = pDevice.Activate(
                        ctypes.wintypes.GUID.from_string(IID_IAudioEndpointVolume),
                        1, None, ctypes.byref(pVolume),
                    )
                    if hr == 0:
                        pVolume.SetMasterVolumeLevelScalar(float(level), None)
                        pVolume.Release()
                    pDevice.Release()
                pEnumerator.Release()
        elif AUDIO_BACKEND == "windows_powershell":
            subprocess.run(
                ["powershell", "-Command",
                 f"$obj = New-Object -ComObject WScript.Shell; "
                 f"1..50 | ForEach-Object {{ $obj.SendKeys([char]174) }}; "
                 f"$obj.SendKeys([char]175)"],
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
        elif AUDIO_BACKEND in ("windows_core", "windows_powershell"):
            r = subprocess.run(
                ["powershell", "-Command",
                 "$w = Get-WmiObject -Class Win32_SoundDevice; "
                 "$v = Get-AudioDevice -PlaybackVolume 2>/dev/null; "
                 "if ($v) { Write-Output $v } else { Write-Output '0.5' }"],
                capture_output=True, text=True,
            )
            try:
                val = float(r.stdout.strip())
                return val if 0.0 <= val <= 1.0 else 0.5
            except ValueError:
                pass
    except Exception:
        pass
    return 0.5


# =====================================================================
#  Utilidades
# =====================================================================

def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    t = max(0.0, min(1.0, t))
    return f"#{int(r1+(r2-r1)*t):02x}{int(g1+(g2-g1)*t):02x}{int(b1+(b2-b1)*t):02x}"


def pil_rounded_rect(size, radius, fill, outline=None, outline_width=0):
    """Draw a rounded rectangle and return a PIL Image."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [(0, 0), (w - 1, h - 1)],
        radius=radius, fill=fill,
        outline=outline, width=outline_width,
    )
    return img


def pil_volume_bar(vol, bar_w, bar_h, accent, accent2, green, orange, red, bg_color, bar_bg):
    """Draw a smooth vertical volume bar with rounded ends and glow."""
    r = bar_w // 2
    img = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background capsule
    draw.rounded_rectangle(
        [(0, 0), (bar_w - 1, bar_h - 1)],
        radius=r, fill=bar_bg,
    )

    # Fill
    inner_h = bar_h - bar_w
    fill_h = max(2, int(vol * inner_h))
    y_top = bar_h - r - fill_h
    y_bot = bar_h - r

    if vol < 0.25:
        color = hex_to_rgb(red)
    elif vol < 0.5:
        color = hex_to_rgb(orange)
    elif vol < 0.75:
        color = hex_to_rgb(accent)
    else:
        color = hex_to_rgb(accent2)

    # Glow layer (wider, blurred)
    glow = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle(
        [(-3, y_top - 3), (bar_w + 3, bar_h - 1 + 3)],
        radius=r + 3, fill=(*color, 60),
    )
    img = Image.alpha_composite(img, glow)

    # Main fill
    fill_layer = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_layer)
    fill_draw.rounded_rectangle(
        [(2, y_top), (bar_w - 2, bar_h - 2)],
        radius=r - 2, fill=(*color, 255),
    )
    img = Image.alpha_composite(img, fill_layer)

    # Inner highlight (top of fill for depth)
    if fill_h > 10:
        highlight = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
        hl_draw = ImageDraw.Draw(highlight)
        hl_draw.rounded_rectangle(
            [(4, y_top + 2), (bar_w - 4, y_top + min(6, fill_h // 3))],
            radius=3, fill=(255, 255, 255, 30),
        )
        img = Image.alpha_composite(img, highlight)

    return img


def pil_button(text, w, h, bg_color, fg_color, radius=10, font_size=12):
    """Draw a pill-shaped button with gradient effect."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = hex_to_rgb(bg_color)
    r2 = hex_to_rgb(bg_color)

    # Subtle vertical gradient
    for y in range(h):
        t = y / h
        c = tuple(int(r[i] + (r2[i] - r[i]) * t * 0.3) for i in range(3))
        draw.line([(0, y), (w - 1, y)], fill=(*c, 255))

    # Rounded rect mask
    mask = Image.new("L", (w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=255)

    # Apply mask
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(img, mask=mask)

    # Text
    draw2 = ImageDraw.Draw(result)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/inter/Inter-Bold.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/TTF/Inter-Bold.ttf", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

    bbox = draw2.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (w - tw) // 2
    ty = (h - th) // 2 - 1
    draw2.text((tx, ty), text, fill=fg_color, font=font)

    return result


def pil_icon_camera(size, color):
    """Play triangle icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = hex_to_rgb(color)
    # Triangle
    margin = size // 5
    points = [
        (margin, margin),
        (size - margin, size // 2),
        (margin, size - margin),
    ]
    draw.polygon(points, fill=(*c, 255))
    return img


def pil_icon_stop(size, color):
    """Stop square icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = hex_to_rgb(color)
    margin = size // 4
    draw.rounded_rectangle(
        [(margin, margin), (size - margin, size - margin)],
        radius=2, fill=(*c, 255),
    )
    return img


def pil_icon_hand(size, color):
    """Hand/palm icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = hex_to_rgb(color)
    # Simplified hand: palm + fingers
    cx, cy = size // 2, size // 2
    r = size // 4
    # Palm
    draw.ellipse([cx - r, cy - r + 2, cx + r, cy + r + 4], fill=(*c, 255))
    # Fingers (small circles)
    fr = size // 8
    for dx in [-r + 2, -r // 2 + 1, r // 2 - 1, r - 2]:
        draw.ellipse([cx + dx - fr, cy - r - fr + 2, cx + dx + fr, cy - r + fr + 2], fill=(*c, 255))
    return img


def pil_icon_wave(size, color):
    """Wave/arrows icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = hex_to_rgb(color)
    cy = size // 2
    lw = max(1, size // 10)
    # Left arrow
    draw.line([(2, cy), (size // 2 - 2, cy)], fill=(*c, 255), width=lw)
    draw.polygon([(2, cy), (size // 4, cy - size // 5), (size // 4, cy + size // 5)], fill=(*c, 255))
    # Right arrow
    draw.line([(size // 2 + 2, cy), (size - 2, cy)], fill=(*c, 255), width=lw)
    draw.polygon([(size - 2, cy), (size * 3 // 4, cy - size // 5), (size * 3 // 4, cy + size // 5)], fill=(*c, 255))
    return img


def pil_icon_volume(size, color):
    """Speaker/volume icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = hex_to_rgb(color)
    lw = max(1, size // 10)
    # Speaker body
    draw.rectangle([size // 5, size // 3, size // 2, size * 2 // 3], fill=(*c, 255))
    # Cone
    draw.polygon([
        (size // 2, size // 4),
        (size * 4 // 5, size // 6),
        (size * 4 // 5, size * 5 // 6),
        (size // 2, size * 3 // 4),
    ], fill=(*c, 255))
    # Sound waves
    for i, r in enumerate([size // 3, size // 2]):
        arc_cx = size // 2
        arc_cy = size // 2
        draw.arc(
            [arc_cx - r, arc_cy - r, arc_cx + r, arc_cy + r],
            start=-40, end=40, fill=(*c, 180 - i * 60), width=lw,
        )
    return img


# =====================================================================
#  Ventana del GIF
# =====================================================================

class GifWindow:
    """Ventana emergente que reproduce un GIF animado con fade-out."""

    def __init__(self, parent: tk.Tk, gif_path: str, on_close=None, preloaded_frames=None):
        self.win = tk.Toplevel(parent)
        self.win.title("")
        self.win.configure(bg="#000000")
        self.win.resizable(False, False)
        self.win.overrideredirect(True)
        self.win.attributes("-alpha", 1.0)
        self._on_close_cb = on_close

        self.frames = preloaded_frames or []
        self.current_frame = 0
        self.playing = True
        self._fading = False
        self._alpha = 1.0

        if not self.frames:
            self._load_gif(gif_path)
        if not self.frames:
            self.win.destroy()
            return

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
        self.win.after(300, self._start_fade)

    def _load_gif(self, path: str):
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
        if not self.playing or not self.frames:
            return
        frame = self.frames[self.current_frame]
        photo = ImageTk.PhotoImage(frame)
        self.label.config(image=photo)
        self.label._photo_ref = photo
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.win.after(50, self._animate)

    def _start_fade(self):
        self._fading = True
        self._fade_step()

    def _fade_step(self):
        if not self.playing:
            return
        self._alpha -= 0.08
        if self._alpha <= 0:
            self.close()
            return
        self.win.attributes("-alpha", self._alpha)
        self.win.after(20, self._fade_step)

    def close(self):
        self.playing = False
        try:
            self.win.destroy()
        except Exception:
            pass
        if self._on_close_cb:
            self._on_close_cb()


# =====================================================================
#  App principal
# =====================================================================

class VolumeApp:
    """App de escritorio para control de volumen por gestos de mano."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Volume Controller")
        self.root.configure(bg=C["bg"])
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Estado de camara
        self.running = False
        self.cap = None
        self.hand_landmarker = None
        self.current_volume = get_volume()
        self.display_volume = self.current_volume
        self.target_volume = self.current_volume
        self.frame_count = 0
        self._photo_ref = None

        # Wave detection
        self.wrist_history = []
        self.wave_cooldown = 0

        # Animacion
        self._pulse = 0.0
        self._gesture_active = False
        self._gesture_color = C["text3"]

        # GIF window reference
        self._gif_win = None

        # GIF frame cache
        self._gif_frames_cache = None

        self._build_ui()
        self._center_window()
        self._start_animation_loop()
        self._preload_gif()

    # -----------------------------------------------------------------
    #  UI profesional
    # -----------------------------------------------------------------

    def _build_ui(self):
        # Fuentes
        try:
            self.font_lg = tkfont.Font(family="Inter", size=36, weight="bold")
            self.font_title = tkfont.Font(family="Inter", size=10, weight="bold")
            self.font_status = tkfont.Font(family="Inter", size=9)
        except Exception:
            self.font_lg = tkfont.Font(family="monospace", size=36, weight="bold")
            self.font_title = tkfont.Font(family="monospace", size=10, weight="bold")
            self.font_status = tkfont.Font(family="monospace", size=9)

        # PIL font for button
        self._btn_font = None
        for fp in [
            "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
            "/usr/share/fonts/TTF/Inter-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]:
            try:
                self._btn_font = ImageFont.truetype(fp, 12)
                break
            except Exception:
                continue
        if self._btn_font is None:
            self._btn_font = ImageFont.load_default()

        # ── Layout principal ──
        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ── Panel izquierdo: camara + barra de estado ──
        left_panel = tk.Frame(outer, bg=C["bg"])
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Panel camara ──
        cam_card = tk.Frame(left_panel, bg=C["card"], bd=0, highlightthickness=0)
        cam_card.pack(fill=tk.BOTH, expand=True)

        # Linea accent superior
        self.accent_bar = tk.Canvas(cam_card, bg=C["card"], highlightthickness=0, height=3)
        self.accent_bar.pack(fill=tk.X)
        self.accent_bar.create_rectangle(0, 0, 2000, 3, fill=C["accent"], outline="")

        # Canvas de camara
        cam_inner = tk.Frame(cam_card, bg=C["surface"])
        cam_inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=(0, 3))

        self.canvas = tk.Canvas(
            cam_inner, bg=C["surface"], highlightthickness=0,
            width=CAM_WIDTH, height=CAM_HEIGHT,
        )
        self.canvas.pack(expand=True)

        # Placeholder icon (PIL-rendered)
        icon_size = 48
        cam_icon = pil_icon_camera(icon_size, C["text3"])
        self._cam_icon_ref = ImageTk.PhotoImage(cam_icon)
        self.placeholder_icon_id = self.canvas.create_image(
            CAM_WIDTH // 2, CAM_HEIGHT // 2 - 16,
            image=self._cam_icon_ref,
        )
        self.placeholder_text_id = self.canvas.create_text(
            CAM_WIDTH // 2, CAM_HEIGHT // 2 + 24,
            text="Iniciar camara", fill=C["text3"],
            font=tkfont.Font(family="Inter", size=14) if "Inter" in tkfont.families()
                  else tkfont.Font(family="monospace", size=14),
        )

        # ── Barra de estado debajo de la camara ──
        status_bar = tk.Frame(left_panel, bg=C["card"], bd=0, highlightthickness=0)
        status_bar.pack(fill=tk.X, pady=(4, 0))

        status_inner = tk.Frame(status_bar, bg=C["card"])
        status_inner.pack(fill=tk.X, padx=12, pady=8)

        # Icono de mano (PIL)
        hand_icon = pil_icon_hand(14, C["text3"])
        self._hand_icon_ref = ImageTk.PhotoImage(hand_icon)
        self.gesture_icon = tk.Label(
            status_inner, image=self._hand_icon_ref, bg=C["card"], bd=0,
        )
        self.gesture_icon.pack(side=tk.LEFT)

        self.gesture_label = tk.Label(
            status_inner, text="Esperando mano", bg=C["card"], fg=C["text3"],
            font=self.font_status, anchor="w",
        )
        self.gesture_label.pack(side=tk.LEFT, padx=(6, 0))

        # Modo
        self.mode_label = tk.Label(
            status_inner, text="Volumen", bg=C["card"], fg=C["text3"],
            font=self.font_status, anchor="w",
        )
        self.mode_label.pack(side=tk.LEFT, padx=(16, 0))

        # Swipe info
        self.swipe_label = tk.Label(
            status_inner, text="Agitar", bg=C["card"], fg=C["text3"],
            font=self.font_status, anchor="w",
        )
        self.swipe_label.pack(side=tk.LEFT, padx=(16, 0))

        # Status a la derecha
        self.status_label = tk.Label(
            status_inner, text="Listo", bg=C["card"], fg=C["green"],
            font=self.font_status, anchor="e",
        )
        self.status_label.pack(side=tk.RIGHT)

        # ── Panel controles (derecha) ──
        right = tk.Frame(outer, bg=C["bg"], width=220)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(20, 0))
        right.pack_propagate(False)

        # Header con icono de volumen (PIL)
        header_frame = tk.Frame(right, bg=C["bg"])
        header_frame.pack(fill=tk.X, pady=(0, 16))

        vol_icon = pil_icon_volume(14, C["text3"])
        self._vol_icon_ref = ImageTk.PhotoImage(vol_icon)
        tk.Label(
            header_frame, image=self._vol_icon_ref, bg=C["bg"], bd=0,
        ).pack(side=tk.LEFT)

        tk.Label(
            header_frame, text="  VOLUME", bg=C["bg"], fg=C["text3"],
            font=self.font_title, anchor="w",
        ).pack(side=tk.LEFT)

        # ── Barra de volumen (PIL) ──
        BAR_W = 52
        BAR_H = 240
        self._bar_w = BAR_W
        self._bar_h = BAR_H

        bar_container = tk.Frame(right, bg=C["bg"])
        bar_container.pack(fill=tk.X, pady=(0, 16))

        self.bar_label = tk.Label(bar_container, bg=C["bg"], bd=0, highlightthickness=0)
        self.bar_label.pack()

        # Render initial bar
        bar_img = pil_volume_bar(
            self.current_volume, BAR_W, BAR_H,
            C["accent"], C["accent2"], C["green"], C["orange"], C["red"],
            C["bg"], C["card"],
        )
        self._bar_img_ref = ImageTk.PhotoImage(bar_img)
        self.bar_label.config(image=self._bar_img_ref)

        # ── Porcentaje ──
        vol_frame = tk.Frame(right, bg=C["bg"])
        vol_frame.pack(fill=tk.X, pady=(0, 4))

        self.vol_label = tk.Label(
            vol_frame, text=f"{int(self.current_volume * 100)}%",
            bg=C["bg"], fg=C["accent"], font=self.font_lg, anchor="w",
        )
        self.vol_label.pack(side=tk.LEFT)

        # ── Boton (PIL) ──
        self.btn_frame = tk.Frame(right, bg=C["bg"])
        self.btn_frame.pack(fill=tk.X, pady=(8, 0))

        self.start_btn = tk.Label(self.btn_frame, bg=C["bg"], bd=0, highlightthickness=0)
        self.start_btn.pack(fill=tk.X)
        self.start_btn.bind("<Button-1>", lambda e: self._toggle_camera())
        self.start_btn.bind("<Enter>", self._btn_enter)
        self.start_btn.bind("<Leave>", self._btn_leave)

        # Render initial button
        self._render_button("start")

    def _render_button(self, state):
        """Render button as PIL image."""
        btn_w = 196
        btn_h = 44
        if state == "start":
            img = pil_button("\u25b6  Iniciar Camara", btn_w, btn_h, C["accent"], "#ffffff", radius=10, font_size=12)
        else:
            img = pil_button("\u23f9  Detener", btn_w, btn_h, C["red"], "#ffffff", radius=10, font_size=12)
        ref = ImageTk.PhotoImage(img)
        self.start_btn.config(image=ref)
        self.start_btn._img_ref = ref

    def _btn_enter(self, e):
        if not self.running:
            btn_w, btn_h = 196, 44
            img = pil_button("\u25b6  Iniciar Camara", btn_w, btn_h, C["accent2"], "#ffffff", radius=10, font_size=12)
            ref = ImageTk.PhotoImage(img)
            self.start_btn.config(image=ref)
            self.start_btn._img_ref = ref

    def _btn_leave(self, e):
        if not self.running:
            self._render_button("start")

    def _update_gesture_icon(self, color):
        """Update gesture hand icon with given color."""
        hand_icon = pil_icon_hand(14, color)
        ref = ImageTk.PhotoImage(hand_icon)
        self.gesture_icon.config(image=ref)
        self.gesture_icon._img_ref = ref

    def _preload_gif(self):
        try:
            gif = Image.open(GIF_PATH)
            frames = []
            while True:
                frame = gif.copy().convert("RGBA")
                frames.append(frame)
                gif.seek(gif.tell() + 1)
            self._gif_frames_cache = frames
        except Exception:
            pass

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

    # -----------------------------------------------------------------
    #  Animacion suave
    # -----------------------------------------------------------------

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

        # Pulso del icono de gesto
        if self._gesture_active:
            self._pulse += 0.12
            p = (math.sin(self._pulse) + 1) / 2
            color = lerp_color(C["accent"], C["accent2"], p)
            hand_icon = pil_icon_hand(14, color)
            ref = ImageTk.PhotoImage(hand_icon)
            self.gesture_icon.config(image=ref)
            self.gesture_icon._img_ref = ref
        else:
            self._pulse = 0.0

    def _render_bar(self, vol: float):
        vol = max(0.0, min(1.0, vol))
        bar_img = pil_volume_bar(
            vol, self._bar_w, self._bar_h,
            C["accent"], C["accent2"], C["green"], C["orange"], C["red"],
            C["bg"], C["card"],
        )
        ref = ImageTk.PhotoImage(bar_img)
        self.bar_label.config(image=ref)
        self.bar_label._img_ref = ref

        pct = int(vol * 100)
        if vol < 0.25:
            color = C["red"]
        elif vol < 0.5:
            color = C["orange"]
        elif vol < 0.75:
            color = C["accent"]
        else:
            color = C["accent2"]
        self.vol_label.config(text=f"{pct}%", fg=color)

    # -----------------------------------------------------------------
    #  Camara y deteccion
    # -----------------------------------------------------------------

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
        self._render_button("stop")
        self.canvas.delete(self.placeholder_icon_id)
        self.canvas.delete(self.placeholder_text_id)
        self.status_label.config(text="Iniciando...", fg=C["orange"])
        threading.Thread(target=self._camera_loop, daemon=True).start()

    def _stop_camera(self):
        self.running = False
        self._render_button("start")
        self.status_label.config(text="Detenido", fg=C["red"])
        self.mode_label.config(text="Volumen", fg=C["text3"])
        self.gesture_label.config(text="Esperando mano", fg=C["text3"])
        hand_icon = pil_icon_hand(14, C["text3"])
        self._hand_icon_ref = ImageTk.PhotoImage(hand_icon)
        self.gesture_icon.config(image=self._hand_icon_ref)
        self.swipe_label.config(text="Agitar", fg=C["text3"])
        self._gesture_active = False
        self.wave_cooldown = 0
        if self.cap:
            self.cap.release()
            self.cap = None
        self.canvas.delete("all")
        cam_icon = pil_icon_camera(48, C["text3"])
        self._cam_icon_ref = ImageTk.PhotoImage(cam_icon)
        self.placeholder_icon_id = self.canvas.create_image(
            CAM_WIDTH // 2, CAM_HEIGHT // 2 - 16,
            image=self._cam_icon_ref,
        )
        self.placeholder_text_id = self.canvas.create_text(
            CAM_WIDTH // 2, CAM_HEIGHT // 2 + 24,
            text="Iniciar camara", fill=C["text3"],
            font=tkfont.Font(family="Inter", size=14) if "Inter" in tkfont.families()
                  else tkfont.Font(family="monospace", size=14),
        )

    def _camera_loop(self):
        try:
            if self.hand_landmarker is None:
                self.root.after(0, lambda: self.status_label.config(
                    text="Cargando modelo...", fg=C["orange"],
                ))
                self._init_model()

            self.cap = cv2.VideoCapture(CAMERA_INDEX)
            if not self.cap.isOpened():
                self.root.after(0, lambda: self.status_label.config(
                    text="Sin camara", fg=C["red"],
                ))
                self.running = False
                return

            self.root.after(0, lambda: self.status_label.config(
                text="Camara activa", fg=C["green"],
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

                    # ── Deteccion de wave ──
                    wave_detected = False
                    if self.wave_cooldown > 0:
                        self.wave_cooldown -= 1
                    else:
                        now = time.time()
                        self.wrist_history.append((wx, now))
                        if len(self.wrist_history) > WAVE_FRAMES_WINDOW:
                            self.wrist_history.pop(0)

                        if len(self.wrist_history) >= 3:
                            t_now = self.wrist_history[-1][1]
                            recent = [(x, t) for x, t in self.wrist_history
                                      if t_now - t <= WAVE_TIME_WINDOW]

                            if len(recent) >= 3:
                                direction_changes = 0
                                for i in range(2, len(recent)):
                                    d1 = recent[i-1][0] - recent[i-2][0]
                                    d2 = recent[i][0] - recent[i-1][0]
                                    if d1 * d2 < 0 and abs(d2) > WAVE_DIRECTION_THRESHOLD:
                                        direction_changes += 1
                                if direction_changes >= WAVE_MIN_CHANGES:
                                    wave_detected = True
                                    self.wave_cooldown = WAVE_COOLDOWN
                                    self.wrist_history.clear()

                    if wave_detected and self._gif_win is None:
                        self.root.after(0, self._show_gif)

                    # ── Dibujar frame ──
                    cv2.circle(frame, (tx, ty), 10, (124, 92, 252), 2)
                    cv2.circle(frame, (ix, iy), 10, (124, 92, 252), 2)

                    if curled:
                        gesture_active = True
                        mode_text = "Volumen"
                        d = math.hypot(ix - tx, iy - ty)
                        vol = max(0.0, min(1.0, (d - 20) / 180))

                        if self.frame_count % 10 == 0:
                            set_volume(vol)
                            self.target_volume = vol
                            self.current_volume = vol

                        cv2.line(frame, (tx, ty), (ix, iy), (0, 230, 118), 3)
                        cv2.line(frame, (tx, ty), (ix, iy), (105, 240, 174), 1)
                    else:
                        mode_text = "Mano abierta"
                        cv2.line(frame, (tx, ty), (ix, iy), (124, 92, 252), 2)

                    # Wave visual feedback
                    if self.wave_cooldown > WAVE_COOLDOWN - 15:
                        cv2.putText(
                            frame, "WAVE!", (w // 2 - 70, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 229, 255), 3,
                        )

                # ── Actualizar UI ──
                self._gesture_active = gesture_active
                m_text = mode_text
                g_color = C["accent"] if gesture_active else C["text3"]
                g_label = (
                    "Gesto activo" if gesture_active
                    else ("Mano detectada" if results.hand_landmarks else "Esperando mano")
                )

                self.root.after(0, lambda mt=m_text, gc=g_color, gl=g_label: (
                    self.mode_label.config(
                        text=mt,
                        fg=C["accent"] if mt == "Volumen" else C["text3"],
                    ),
                    self._update_gesture_icon(gc),
                    self.gesture_label.config(text=gl, fg=gc),
                    self.swipe_label.config(
                        text="Wave!" if self.wave_cooldown > WAVE_COOLDOWN - 20
                        else "Agitar",
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
                self.status_label.config(text=f"Error: {msg}", fg=C["red"]))
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
        if self._gif_win is not None:
            try:
                if self._gif_win.win.winfo_exists():
                    return
            except Exception:
                pass
        self._gif_win = GifWindow(
            self.root, GIF_PATH,
            on_close=self._on_gif_closed,
            preloaded_frames=self._gif_frames_cache,
        )

    def _on_gif_closed(self):
        self._gif_win = None

    # -----------------------------------------------------------------
    #  Cierre
    # -----------------------------------------------------------------

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
