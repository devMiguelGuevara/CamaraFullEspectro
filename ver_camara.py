"""Visor en vivo de la cámara full espectro (por defecto la D-Link DSB-C120),
con modos de visualización espectral (ver espectro.py).

Uso:
    python ver_camara.py                     # busca "DSB-C120" por nombre
    python ver_camara.py --nombre Camo       # otra cámara, por parte del nombre
    python ver_camara.py --indice 2          # o directamente por índice

Teclas:
    1-9, 0, e, t  modo: crudo, balance de blancos, IR B/N, IR falso color,
         mapa IR, detección NIR, NDVI, canales, fuentes IR, venas,
         espectro comprimido, traducción NIR
    m    siguiente modo              a  autoajuste sí/no
    d    reducción de ruido sí/no    s  guardar foto (original + modo actual)
    c    propiedades del driver      q  salir
"""
import argparse
import os
import sys
import time
from datetime import datetime

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2

from detectar_camaras import nombres_dshow
from espectro import MODOS, TECLAS, Niveles, Suavizado, procesar

CARPETA_FOTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")
AYUDA = "1-9,0,e,t modo  m sig.  a auto  d ruido  s foto  c driver  q salir"


def buscar_indice(parte_nombre):
    nombres = nombres_dshow()
    for i, nombre in enumerate(nombres):
        if parte_nombre.lower() in nombre.lower():
            return i, nombre
    print(f"No hay ninguna cámara cuyo nombre contenga '{parte_nombre}'.")
    print("Cámaras disponibles:", ", ".join(nombres) or "(ninguna; ¿está ffmpeg instalado?)")
    sys.exit(1)


def texto(img, linea, y, color=(0, 255, 0)):
    """Texto con franja oscura detrás para que se lea sobre cualquier fondo."""
    (w, h), _ = cv2.getTextSize(linea, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(img, (0, y - h - 6), (w + 10, y + 5), (0, 0, 0), -1)
    cv2.putText(img, linea, (5, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--nombre", default="DSB-C120", help="parte del nombre de la cámara")
    ap.add_argument("--indice", type=int, help="índice DirectShow (ignora --nombre)")
    ap.add_argument("--ancho", type=int, default=352, help="352x288 es la resolución nativa del sensor")
    ap.add_argument("--alto", type=int, default=288)
    ap.add_argument("--zoom", type=float, default=2.0, help="escala de la ventana")
    ap.add_argument("--modo", type=int, default=1, choices=range(1, len(MODOS) + 1),
                    help="modo inicial")
    args = ap.parse_args()

    if args.indice is None:
        indice, nombre = buscar_indice(args.nombre)
    else:
        indice, nombre = args.indice, f"indice {args.indice}"

    cap = cv2.VideoCapture(indice, cv2.CAP_DSHOW, [
        cv2.CAP_PROP_FRAME_WIDTH, args.ancho, cv2.CAP_PROP_FRAME_HEIGHT, args.alto])
    if not cap.isOpened():
        print(f"No se pudo abrir {nombre}. Si acabas de conectarla, espera unos segundos y reintenta.")
        sys.exit(1)

    ancho, alto = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Mostrando {nombre} ({ancho}x{alto}). {AYUDA}")
    ventana = f"{nombre} | {AYUDA}"  # la ayuda va en el título para no tapar las leyendas
    niv, suav = Niveles(), Suavizado()
    modo, ruido = args.modo - 1, True
    t_prev, fps, negros = time.time(), 0.0, 0

    while True:
        ok, frame = cap.read()
        if not ok:
            print("La cámara dejó de enviar imagen.")
            break

        ahora = time.time()
        fps = 0.9 * fps + 0.1 / max(ahora - t_prev, 1e-6)
        t_prev = ahora
        negros = negros + 1 if frame.mean() < 0.3 else 0  # sensor colgado ~0.0; cuarto oscuro 1-15

        procesada = procesar(frame, modo, niv, suav if ruido else None)
        vista = cv2.resize(procesada, None, fx=args.zoom, fy=args.zoom, interpolation=cv2.INTER_LINEAR)
        texto(vista, f"{modo + 1} {MODOS[modo][0]} | {fps:4.1f} fps | auto {'SI' if niv.activo else 'NO'}"
                     f" | ruido {'SI' if ruido else 'NO'}", 20)
        if negros > 15:
            texto(vista, "Imagen negra: lente tapado? Si hay luz, reconecta la camara", 44, (0, 0, 255))
        cv2.imshow(ventana, vista)

        tecla = cv2.waitKey(1) & 0xFF
        if tecla in (ord("q"), 27) or cv2.getWindowProperty(ventana, cv2.WND_PROP_VISIBLE) < 1:
            break
        if chr(tecla) in TECLAS[:len(MODOS)]:
            modo = TECLAS.index(chr(tecla))
        elif tecla == ord("m"):
            modo = (modo + 1) % len(MODOS)
        elif tecla == ord("a"):
            niv.activo = not niv.activo
        elif tecla == ord("d"):
            ruido = not ruido
            suav.acumulado = None
        elif tecla == ord("c"):
            cap.set(cv2.CAP_PROP_SETTINGS, 1)  # abre el panel de propiedades del driver
        elif tecla == ord("s"):
            os.makedirs(CARPETA_FOTOS, exist_ok=True)
            base = os.path.join(CARPETA_FOTOS, datetime.now().strftime("foto_%Y%m%d_%H%M%S"))
            cv2.imwrite(base + "_original.png", frame)
            cv2.imwrite(base + f"_modo{modo + 1}.png", procesada)
            print("Guardadas:", base + "_original.png", "y", f"_modo{modo + 1}.png")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
