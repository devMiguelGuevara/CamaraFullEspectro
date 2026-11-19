# Cámara Full Espectro

Visor en vivo para una webcam modificada **sin filtro de corte IR**, con 12 modos de visualización espectral e infrarroja. Probado con una D-Link DSB-C120 (chip PixArt PAC207).

Un sensor RGB sin filtro IR suma el infrarrojo cercano (NIR, ~700–1000 nm) a sus tres canales. Este proyecto procesa la imagen en tiempo real para hacer visible lo que el ojo no ve.

## Modos

| Tecla | Modo | Qué muestra |
|---|---|---|
| `1` | Full espectro (crudo) | Lo que ve el sensor, con la proporción real entre canales |
| `2` | Balance de blancos | Cada canal nivelado por separado, para acercarse a colores naturales |
| `3` | Infrarrojo B/N | Canal rojo (el más sensible al NIR) con realce de contraste local |
| `4` | IR falso color | Falso color clásico de fotografía IR (rojo y azul intercambiados) |
| `5` | Mapa de intensidad IR | Intensidad rojo/NIR con escala de color |
| `6` | Detección NIR | Resalta lo que refleja mucho infrarrojo (vegetación, piel, telas) |
| `7` | NDVI vegetación | Índice de vegetación sana, estilo Infragram |
| `8` | Canales | Mosaico 2×2: R+NIR, G, B y exceso de NIR |
| `9` | Fuentes IR | Marca LEDs infrarrojos y distingue los que parpadean (prueba con un control remoto) |
| `0` | Venas NIR | Las venas se ven oscuras porque la sangre absorbe el NIR |
| `e` | Espectro comprimido | Lleva 400–1000 nm al rango visible 380–700 nm |
| `t` | Traducción NIR | Desplaza 700–1000 nm a colores visibles; clic en la imagen para leer la longitud de onda |

> Los modos son aproximaciones o falso color. Con un filtro óptico delante del lente (IR 720 nm, o azul Rosco 2007 para NDVI) pasan a ser mediciones reales. No es imagen térmica: es luz infrarroja reflejada, no calor.

## Instalación

Windows (usa DirectShow y APIs de Windows) con Python 3.13:

```powershell
pip install -r requirements.txt
```

## Uso

```powershell
python interfaz.py          # interfaz gráfica (o doble clic en "Abrir camara.bat")
python ver_camara.py        # visor simple en ventana OpenCV
python ver_camara.py --nombre Camo   # otra cámara, por parte del nombre
python ver_camara.py --indice 2      # o por índice
```

Atajos en la interfaz: teclas de modo de la tabla · `a` autoajuste · `c` comparar con el original · `espacio` foto · `g` grabar video. Las fotos se guardan en `capturas/`.

## Diagnóstico USB

La PAC207 no tiene driver oficial en Windows moderno. Para investigar la cámara:

| Script | Qué hace |
|---|---|
| `detectar_camaras.py` | Lista dispositivos USB, cámaras registradas en Windows e índices usables por OpenCV |
| `consultar_usb.py [VID:PID] [--led]` | Lee descriptores USB con libusb y el ID del chip PAC207 (requiere el driver libusbK, instalable con [Zadig](https://zadig.akeo.ie)) |
| `puertos_usb.py` | Estado eléctrico de cada puerto USB: distingue un puerto vacío de un dispositivo que falla al enumerarse |

## Estructura

| Archivo | Función |
|---|---|
| `espectro.py` | Núcleo: los 12 modos, autoajuste de niveles y reducción de ruido |
| `interfaz.py` | Interfaz Tkinter con captura en hilo aparte, sonda de longitud de onda, fotos y video |
| `ver_camara.py` | Visor alternativo sin interfaz |
