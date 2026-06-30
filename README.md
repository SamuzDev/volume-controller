# Volume Controller - Camera Gesture Volume Control

App de escritorio que controla el volumen del sistema usando gestos de mano detectados por la camara web. Creada con tkinter + PIL para renderizado en tiempo real.

## Requisitos

- Python 3.10+
- Webcam funcional
- Linux con PipeWire (`wpctl`) o ALSA (`amixer`)
- Windows 10/11 (volumen nativo via Core Audio API)

## Instalacion

### Linux

```bash
cd volume-controller
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Windows

```powershell
cd volume-controller
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> **Nota:** En Windows, asegurate de tener Python 3.10+ instalado y disponible en el PATH. Puedes descargarlo desde [python.org](https://www.python.org/downloads/).

## Ejecucion

### Linux
```bash
python main.py
```

### Windows
```powershell
python main.py
```

## Como funciona

1. Presiona **"Iniciar Camara"** para activar la camara
2. Haz un gesto de **pinch** (pulgar + indice juntos) para controlar el volumen
3. La distancia entre los dedos determina el nivel de volumen:
   - Dedos juntos -> volumen bajo
   - Dedos separados -> volumen alto
4. Los dedos medio, anular y menique deben estar doblados para activar el modo volumen

## Controles

| Gesto | Accion |
|-------|--------|
| Pinch (pulgar + indice) | Controlar volumen |
| Mano abierta | Sin accion |
| Agitar mano (wave) | Animacion GIF |

## Arquitectura

```
tkinter UI (Canvas) <---> CameraController (thread) --> OpenCV --> MediaPipe HandLandmarker
                                                                    |
                                                          Gesture Detection (pinch)
                                                                    |
                                                    System Command (wpctl/amixer/Windows Core Audio)
```

## Estructura del proyecto

```
volume-controller/
├── main.py                 # App tkinter principal
├── assets/
│   ├── hand_landmarker.task    # Modelo ML para deteccion de manos
│   └── scuba-scuba-cat.gif     # Animacion para wave
├── requirements.txt        # Dependencias
└── README.md               # Esta documentacion
```

## Componentes principales

### VolumeControllerApp (tkinter)
- Interfaz grafica con tkinter (Canvas para camara, Labels para texto)
- Renderizado en tiempo real usando PIL ImageTk (30fps)
- Diseno oscuro elegante con panel lateral de controles

### CameraController (hilo)
- Ejecuta la captura de camara en un hilo separado
- Inicializa MediaPipe HandLandmarker con el modelo local
- Detecta landmarks de la mano (21 puntos)
- Calcula gestos y ejecuta comandos de volumen
- Convierte frames OpenCV -> PIL -> ImageTk para mostrar en Canvas

## Landmarks utilizados

| Indice | Punto | Uso |
|--------|-------|-----|
| 0 | Muneca | Referencia para doblez de dedos |
| 4 | Punta del pulgar | Calculo de distancia (pinch) |
| 8 | Punta del indice | Calculo de distancia (pinch) |
| 9 | Nudillo medio | Referencia de doblez |
| 12 | Punta medio | Referencia de doblez |
| 13 | Nudillo anular | Referencia de doblez |
| 16 | Punta anular | Referencia de doblez |
| 17 | Nudillo menique | Referencia de doblez |
| 20 | Punta menique | Referencia de doblez |

## Deteccion de modo

El script verifica si los dedos medio, anular y menique estan doblados comparando:
- Distancia punta-muneca vs. distancia nudillo-muneca
- Si punta-muneca < nudillo-muneca x 0.85 -> dedo doblado

| Dedos doblados | Modo |
|----------------|------|
| Los 3 doblados | Volumen (pinch controla nivel) |
| Al menos 1 extendido | Idle (sin accion) |

## Backend de audio

Deteccion automatica al inicio:

### Linux
1. **PipeWire** (`wpctl`) -- preferido
2. **ALSA** (`amixer`) -- fallback

### Windows
1. **Core Audio API** (via ctypes) -- preferido
2. **WScript.Shell** (fallback por teclado de volumen)

## Dependencias

| Paquete | Version | Proposito |
|---------|---------|-----------|
| opencv-python | >=4.10.0 | Captura y procesamiento de imagen |
| opencv-contrib-python | >=4.10.0 | Modulos adicionales de OpenCV |
| mediapipe | >=0.10.18 | Deteccion de landmarks de mano |
| numpy | >=1.26.0 | Arrays numericos |
| Pillow | >=10.0.0 | Conversion de imagenes para tkinter |

## Troubleshooting

| Problema | Solucion |
|----------|----------|
| `No module named 'cv2'` | `pip install opencv-python opencv-contrib-python` |
| `No module named 'mediapipe'` | `pip install mediapipe` |
| `hand_landmarker.task not found` | Verificar que el archivo este en la misma carpeta que main.py |
| `Cannot open camera` | Cerrar otras apps que usen la camara |
| `amixer: command not found` | Instalar `alsa-utils` o usar PipeWire |
| `No module named 'PIL'` | `pip install Pillow` |
| Camara lenta | Verificar que no haya otros procesos usando la camara |
| Windows: `Access denied` al cambiar volumen | Ejecutar como administrador |

## Por que no Flet

Flet no es adecuado para video en tiempo real porque:
- Cada frame requiere serializar a base64 -> enviar al engine Flutter -> deserializar
- `page.update()` envia todo el estado de la UI, no solo el frame
- Resultado: ~2-5fps vs 30fps con tkinter

## Mejoras posibles

- Control de musica (next/previous) con swipe
- Modo mute con gesto de puno
- Calibracion automatica de rangos
- Soporte para multiples manos
- Indicador visual de landmarks en la UI
