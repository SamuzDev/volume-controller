# Volume Controller - Camera Gesture Volume Control

App de escritorio que controla el volumen del sistema usando gestos de mano detectados por la cámara web. Creada con tkinter + PIL para renderizado en tiempo real.

## Requisitos

- Python 3.10+
- Webcam funcional
- Linux con PipeWire (`wpctl`) o ALSA (`amixer`)

## Instalación

```bash
cd volume-controller
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Ejecución

```bash
python main.py
```

## Cómo funciona

1. Presiona **"Iniciar Camara"** para activar la cámara
2. Haz un gesto de **pinch** (pulgar + índice juntos) para controlar el volumen
3. La distancia entre los dedos determina el nivel de volumen:
   - Dedos juntos → volumen bajo
   - Dedos separados → volumen alto
4. Los dedos medio, anular y meñique deben estar doblados para activar el modo volumen

## Arquitectura

```
tkinter UI (Canvas) ←→ CameraController (thread) → OpenCV → MediaPipe HandLandmarker
                                                                    ↓
                                                          Gesture Detection (pinch)
                                                                    ↓
                                                          System Command (wpctl/amixer)
```

## Estructura del proyecto

```
volume-controller/
├── main.py                 # App tkinter principal
├── hand_landmarker.task    # Modelo ML para detección de manos
├── requirements.txt        # Dependencias
└── README.md               # Esta documentación
```

## Componentes principales

### VolumeControllerApp (tkinter)
- Interfaz gráfica con tkinter (Canvas para cámara, Labels para texto)
- Renderizado en tiempo real usando PIL ImageTk (30fps)
- Diseño oscuro con panel lateral de controles

### CameraController (hilo)
- Ejecuta la captura de cámara en un hilo separado
- Inicializa MediaPipe HandLandmarker con el modelo local
- Detecta landmarks de la mano (21 puntos)
- Calcula gestos y ejecuta comandos de volumen
- Convierte frames OpenCV → PIL → ImageTk para mostrar en Canvas

## Landmarks utilizados

| Índice | Punto | Uso |
|--------|-------|-----|
| 0 | Muñeca | Referencia para doblez de dedos |
| 4 | Punta del pulgar | Cálculo de distancia (pinch) |
| 8 | Punta del índice | Cálculo de distancia (pinch) |
| 9 | Nudillo medio | Referencia de doblez |
| 12 | Punta medio | Referencia de doblez |
| 13 | Nudillo anular | Referencia de doblez |
| 16 | Punta anular | Referencia de doblez |
| 17 | Nudillo meñique | Referencia de doblez |
| 20 | Punta meñique | Referencia de doblez |

## Detección de modo

El script verifica si los dedos medio, anular y meñique están doblados comparando:
- Distancia punta-muñeca vs. distancia nudillo-muñeca
- Si punta-muñeca < nudillo-muñeca × 0.85 → dedo doblado

| Dedos doblados | Modo |
|----------------|------|
| Los 3 doblados | Volumen (pinch controla nivel) |
| Al menos 1 extendido | Idle (sin acción) |

## Backend de audio

Detección automática al inicio:
1. **PipeWire** (`wpctl`) — preferido
2. **ALSA** (`amixer`) — fallback

## Dependencias

| Paquete | Versión | Propósito |
|---------|---------|-----------|
| opencv-python | ≥4.10.0 | Captura y procesamiento de imagen |
| opencv-contrib-python | ≥4.10.0 | Módulos adicionales de OpenCV |
| mediapipe | ≥0.10.18 | Detección de landmarks de mano |
| numpy | ≥1.26.0 | Arrays numéricos |
| Pillow | ≥10.0.0 | Conversión de imágenes para tkinter |

## Troubleshooting

| Problema | Solución |
|----------|----------|
| `No module named 'cv2'` | `pip install opencv-python opencv-contrib-python` |
| `No module named 'mediapipe'` | `pip install mediapipe` |
| `hand_landmarker.task not found` | Verificar que el archivo esté en la misma carpeta que main.py |
| `Cannot open camera` | Cerrar otras apps que usen la cámara |
| `amixer: command not found` | Instalar `alsa-utils` o usar PipeWire |
| `No module named 'PIL'` | `pip install Pillow` |
| Cámara lenta | Verificar que no haya otros procesos usando la cámara |

## Por qué no Flet

Flet no es adecuado para video en tiempo real porque:
- Cada frame requiere serializar a base64 → enviar al engine Flutter → deserializar
- `page.update()` envía todo el estado de la UI, no solo el frame
- Resultado: ~2-5fps vs 30fps con tkinter

## Mejoras posibles

- Control de música (next/previous) con swipe
- Modo mute con gesto de puño
- Calibración automática de rangos
- Soporte para múltiples manos
- Indicador visual de landmarks en la UI
