# Cámara Full Espectro · Agente maestro

> Visor en vivo para una webcam modificada sin filtro IR (D-Link DSB-C120, chip PixArt PAC207), con 12 modos de visualización espectral e infrarroja.

## Qué hace

Toma la imagen de una cámara "full espectro" (sensor RGB que también capta infrarrojo cercano, 700–1000 nm) y la procesa en tiempo real para hacer visible lo que el ojo no ve. Incluye modos de fotografía IR, índice de vegetación (NDVI), detección de fuentes IR (por ejemplo el LED de un control remoto), realce de venas y "traducción" del infrarrojo a colores visibles. Al hacer clic en la imagen, una sonda estima la longitud de onda de ese punto.

También trae herramientas de diagnóstico USB para cuando Windows no reconoce la cámara (no hay driver oficial para la PAC207).

## Estado

**Activo y funcional.** Última modificación: 11-sep-2026. Hay capturas de prueba en `capturas/`.

## Cómo se usa

```powershell
# Interfaz gráfica (recomendado): doble clic en "Abrir camara.bat"  o
python interfaz.py

# Visor simple en ventana OpenCV
python ver_camara.py                  # busca la DSB-C120 por nombre
python ver_camara.py --indice 2       # otra cámara por índice

# Diagnóstico
python detectar_camaras.py            # USB conectados + cámaras de Windows + índices de OpenCV
python consultar_usb.py [VID:PID]     # descriptores USB a bajo nivel (libusb)
python puertos_usb.py                 # estado eléctrico de cada puerto USB
```

Atajos en la interfaz: `1-9`, `0`, `e`, `t` cambian de modo · `a` autoajuste · `c` comparar con el original · `espacio` foto · `g` grabar video.

## Archivos clave

| Archivo | Función |
|---|---|
| `interfaz.py` | GUI Tkinter: video en vivo en un hilo aparte, modos, sonda, fotos y video (MJPG) |
| `espectro.py` | Núcleo: los 12 modos de procesado (`MODOS`), autoajuste de niveles y reducción de ruido |
| `ver_camara.py` | Visor alternativo sin GUI (ventana OpenCV + teclado) |
| `detectar_camaras.py` | Detección de cámaras y tabla de IDs USB de la PAC207 |
| `consultar_usb.py` | Habla con el chip PAC207 por libusb (necesita driver libusbK vía Zadig) |
| `puertos_usb.py` | Lee el estado de los puertos USB con la API de Windows (ctypes) |
| `Abrir camara.bat` | Lanza la interfaz sin consola (`pythonw`) |
| `capturas/` | Fotos guardadas (original + modo aplicado) |

Modos (`espectro.MODOS`): crudo, balance de blancos, IR B/N, IR falso color, mapa de intensidad IR, detección NIR, NDVI, canales, fuentes IR, venas NIR, espectro comprimido, traducción NIR.

## Dependencias

En `requirements.txt`, probadas con el Python 3.13 del sistema (`C:\Python313`, el que usa `Abrir camara.bat`): `opencv-python 5.0.0.93`, `numpy 2.5.3`, `Pillow 12.2.0`, `libusb1 3.4.0` (módulo `usb1`, solo para `consultar_usb.py`). Solo Windows (usa DirectShow y APIs de Windows). No tiene entorno virtual propio.

## Cambios del 19-nov-2026

- Se agregó `requirements.txt`. Todos los scripts ya tenían descripción al inicio.

## Observaciones y pendientes

- Los modos IR son aproximaciones sin un filtro óptico real (IR 720 nm o azul Rosco 2007); el propio código lo advierte. En la interfaz hay un ajuste para indicar que el filtro está puesto.
- No es imagen térmica: es infrarrojo cercano reflejado.

## Reglas para el agente

- Todo el código y los textos visibles están en español; mantenerlo así.
- Un modo nuevo es una función `modo_x(img, niv)` que recibe BGR float32 (0..1) y devuelve BGR uint8; se registra en `MODOS` y se le asigna tecla en `TECLAS`.
- La captura de video solo se toca desde el hilo `Camara` (DirectShow); la interfaz le envía órdenes por la cola `ordenes`.
