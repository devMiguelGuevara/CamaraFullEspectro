"""Modos de visualización para una cámara full espectro (sin filtro de corte IR).

Un sensor RGB sin filtro IR suma a sus tres canales el infrarrojo cercano
(NIR, ~700-1000 nm), y el canal rojo es el más sensible. Sin filtros ópticos
delante del lente no se puede separar el NIR del visible con exactitud, así que
estos modos son aproximaciones o falso color. Con filtros (IR 720 nm, azul
Rosco 2007 para NDVI...) pasan a ser mediciones reales.

Nada de esto es imagen térmica: es luz infrarroja cercana reflejada, no calor.
"""
import colorsys

import cv2
import numpy as np

# Tabla de longitudes de onda visibles (nm) y el nombre de su color
BANDAS_VISIBLES = [
    (380, 450, "Violeta"), (450, 495, "Azul"), (495, 570, "Verde"),
    (570, 590, "Amarillo"), (590, 620, "Naranja"), (620, 700, "Rojo"),
]
RANGO_SENSOR = (400, 1000)  # lo que capta el silicio sin filtro IR
RANGO_VISIBLE = (380, 700)
CENTROS_BANDAS = {"B": 460, "G": 540, "R": 610, "NIR": 850}  # nm aproximados

# ¿Hay un filtro IR 720 nm delante del lente? Lo cambia la interfaz.
CONFIG = {"filtro_ir": False}
# Cociente (G+B)/2R de la parte IR: ~0.15 cerca de 700 nm (solo responde el
# canal rojo) y ~0.95 desde ~850-1000 nm (los tres canales por igual). Son
# valores típicos de sensores CMOS; se pueden calibrar con LEDs de 850/940 nm.
Q_IR = (0.15, 0.95)


def nombre_color(nm):
    for desde, hasta, nombre in BANDAS_VISIBLES:
        if desde <= nm < hasta:
            return nombre
    return "Infrarrojo (no visible)" if nm >= 700 else "Ultravioleta (no visible)"


def longitud_a_bgr(nm):
    """Color aproximado (BGR 0..1) de una longitud de onda visible, según el
    algoritmo de Dan Bruton. Devuelve None fuera del visible (380-700 nm)."""
    if not RANGO_VISIBLE[0] <= nm <= RANGO_VISIBLE[1]:
        return None
    if nm < 440:
        r, g, b = (440 - nm) / 60, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, (510 - nm) / 20
    elif nm < 580:
        r, g, b = (nm - 510) / 70, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, (645 - nm) / 65, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    brillo = 0.3 + 0.7 * (nm - 380) / 40 if nm < 420 else 1.0  # el ojo ve poco el violeta extremo
    return b * brillo, g * brillo, r * brillo


def comprimir(nm):
    """Lleva una longitud de onda del rango del sensor al rango visible."""
    (a, b), (c, d) = RANGO_SENSOR, RANGO_VISIBLE
    return c + (nm - a) * (d - c) / (b - a)


def describir_color(bgr):
    """Longitud de onda dominante aproximada de un color del sensor (BGR 0..1),
    estimada por su tono. Blancos, grises y magentas no corresponden a una sola
    longitud de onda, y en esta cámara el IR suele verse justamente así."""
    b, g, r = (float(v) for v in bgr)
    maximo, minimo = max(b, g, r), min(b, g, r)
    if maximo < 0.04:
        return "demasiado oscuro para estimar"
    if (maximo - minimo) / maximo < 0.2:
        return "sin tono dominante: blanco/gris o mezcla amplia (en esta cámara, a menudo IR)"
    tono = colorsys.rgb_to_hsv(r, g, b)[0] * 360
    if 270 < tono < 340:
        return "magenta: mezcla de rojo y azul, no es una sola longitud (en esta cámara suele ser IR)"
    if tono >= 340:
        tono -= 360
    nm = float(np.interp(tono, [-20, 0, 30, 60, 120, 180, 240, 270],
                         [680, 650, 600, 578, 530, 490, 460, 420]))
    texto = f"~{nm:.0f} nm, {nombre_color(nm)}"
    if nm >= 590:
        texto += " (en esta cámara el rojo también incluye NIR)"
    return texto


def posicion_ir(img):
    """Estima la longitud de onda IR dominante de cada píxel (700-1000 nm) a partir
    de cómo responden los tres filtros de color en el infrarrojo: cerca de
    700-750 nm casi solo el rojo, desde ~850 nm los tres por igual. Solo es
    fiable con un filtro IR 720 nm que bloquee el visible.
    Devuelve (longitud de onda, intensidad)."""
    b, g, r = cv2.split(img)
    q = (g + b) / (2 * r + 1e-3)
    t = np.clip((q - Q_IR[0]) / (Q_IR[1] - Q_IR[0]), 0, 1)
    return 700 + 300 * t, np.maximum(np.maximum(b, g), r)


def describir_ir(bgr):
    """Longitud de onda IR estimada de un píxel y el color artificial con que la
    muestra el modo Traducción NIR."""
    lam, intensidad = posicion_ir(np.asarray(bgr, np.float32).reshape(1, 1, 3))
    lam, intensidad = float(lam[0, 0]), float(intensidad[0, 0])
    if intensidad < 0.04:
        return "IR: demasiado oscuro para estimar"
    mostrado = min(lam - 300, 699.9)  # 1000 nm cae justo en el borde del rojo
    texto = f"IR estimado ~{lam:.0f} nm, mostrado como {nombre_color(mostrado).lower()}"
    return texto + ("" if CONFIG["filtro_ir"] else " (orientativo: sin filtro IR 720)")


class Niveles:
    """Autoajuste por software: estira cada imagen a 0..1 según sus percentiles,
    suavizando entre cuadros para que el brillo no parpadee. Apagado, usa un
    rango fijo y los valores se ven tal cual llegan."""

    def __init__(self, suavizado=0.15):
        self.suavizado = suavizado
        self.activo = True
        self.estado = {}

    def __call__(self, clave, x, por_canal=False, bajo=1.0, alto=99.5, fijo=(0.0, 1.0),
                 desde_cero=False):
        """desde_cero=True deja el negro en 0 y solo ajusta el blanco: el brillo
        sigue representando la intensidad real."""
        if not self.activo:
            lo, hi = fijo
        else:
            muestra = x[::4, ::4]
            eje = (0, 1) if (x.ndim == 3 and por_canal) else None
            hi = np.percentile(muestra, alto, axis=eje)
            lo = 0.0 * hi if desde_cero else np.percentile(muestra, bajo, axis=eje)
            lo = np.minimum(lo, hi - 0.02)  # una imagen uniforme no debe quedar en negro
            if clave in self.estado:
                plo, phi = self.estado[clave]
                lo = plo + self.suavizado * (lo - plo)
                hi = phi + self.suavizado * (hi - phi)
            self.estado[clave] = (lo, hi)
        return np.clip((x - lo) / np.maximum(hi - lo, 1e-4), 0.0, 1.0)


class Suavizado:
    """Promedio temporal de cuadros: reduce el ruido con poca luz (deja estela
    si algo se mueve)."""

    def __init__(self, peso_nuevo=0.3):
        self.peso = peso_nuevo
        self.acumulado = None

    def __call__(self, img):
        if self.acumulado is None or self.acumulado.shape != img.shape:
            self.acumulado = img.copy()
        else:
            cv2.accumulateWeighted(img, self.acumulado, self.peso)
        return self.acumulado


def a_u8(x):
    return np.ascontiguousarray(np.clip(x, 0, 1) * 255, dtype=np.uint8)


def gris_a_bgr(x):
    return cv2.cvtColor(a_u8(x), cv2.COLOR_GRAY2BGR)


def colorear(x, mapa=cv2.COLORMAP_INFERNO):
    return cv2.applyColorMap(a_u8(x), mapa)


_clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(6, 6))
_clahe_fuerte = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
FUENTE = cv2.FONT_HERSHEY_SIMPLEX


def exceso_rojo(img):
    """Cuánto domina el canal rojo (rojo + NIR) sobre verde y azul. Resalta lo
    que refleja mucho infrarrojo: vegetación, piel, muchas telas y tintes."""
    b, g, r = cv2.split(img)
    return cv2.GaussianBlur(np.maximum(r - (g + b) / 2, 0), (5, 5), 0)  # el difuminado quita el moteado del ruido


# --- Modos: cada uno recibe la imagen BGR float32 (0..1) y devuelve BGR uint8 ---

def modo_crudo(img, niv):
    """Lo que ve el sensor, con un solo nivel para los tres canales: conserva
    la proporción real entre canales (de ahí el tono rojizo)."""
    return a_u8(niv("crudo", img))


def modo_balance(img, niv):
    """Nivela cada canal por separado (balance de blancos automático). Es lo que
    hacen los fotógrafos full espectro para acercarse a colores naturales."""
    return a_u8(niv("balance", img, por_canal=True))


def modo_ir(img, niv):
    """Infrarrojo en blanco y negro: canal rojo (el más sensible al NIR) con
    realce de contraste local. Con un filtro IR 720 nm es infrarrojo puro."""
    r = niv("ir", img[:, :, 2])
    return cv2.cvtColor(_clahe.apply(a_u8(r)), cv2.COLOR_GRAY2BGR)


def modo_ir_falso_color(img, niv):
    """Falso color clásico de fotografía IR: balance de blancos y luego
    intercambio de los canales rojo y azul."""
    return a_u8(niv("falso", img, por_canal=True)[:, :, ::-1])


def modo_mapa_ir(img, niv):
    """Intensidad del canal rojo/NIR traída al visible con una escala de color
    (oscuro -> morado -> naranja -> amarillo)."""
    return colorear(niv("mapa", img[:, :, 2]), cv2.COLORMAP_INFERNO)


def modo_deteccion(img, niv):
    """Detección NIR: pinta sobre la imagen en gris las zonas donde el
    rojo/infrarrojo domina a los demás canales."""
    base = gris_a_bgr(niv("det_base", cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))
    ex = niv("det_exceso", exceso_rojo(img), bajo=50, alto=99.5, fijo=(0.0, 0.5))
    capa = colorear(ex, cv2.COLORMAP_TURBO)
    alfa = ex[:, :, None]
    return (base * (1 - alfa) + capa * alfa).astype(np.uint8)


def modo_ndvi(img, niv):
    """NDVI = (NIR - azul) / (NIR + azul), índice de vegetación sana (estilo
    Infragram). Pensado para usarse con filtro azul (Rosco 2007): entonces el
    canal rojo es casi solo NIR. Sin filtro, úsalo como contraste relativo."""
    b, _, r = cv2.split(cv2.GaussianBlur(img, (5, 5), 0))
    suma = r + b
    ndvi = (r - b) / (suma + 1e-3)
    oscuro = suma < 0.04  # demasiado oscuro para medir: el cociente sería puro ruido
    medible = ndvi[~oscuro]
    if medible.size:
        ndvi[oscuro] = medible.min()
    salida = colorear(niv("ndvi", ndvi, bajo=2, alto=98, fijo=(-1.0, 1.0)), cv2.COLORMAP_TURBO)
    salida[oscuro] = 0
    return salida


def modo_canales(img, niv):
    """Mosaico 2x2: canal rojo(+NIR), verde, azul y exceso de rojo/NIR."""
    h, w = img.shape[:2]
    b, g, r = cv2.split(niv("canales", img))  # un nivel común: se comparan entre sí
    ex = niv("canales_ex", exceso_rojo(img), fijo=(0.0, 0.5))
    celdas = [(gris_a_bgr(r), "R + NIR"), (gris_a_bgr(g), "G"),
              (gris_a_bgr(b), "B"), (colorear(ex, cv2.COLORMAP_TURBO), "exceso NIR")]
    peq = []
    for celda, texto in celdas:
        c = cv2.resize(celda, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        cv2.putText(c, texto, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)
        peq.append(c)
    return np.vstack([np.hstack(peq[:2]), np.hstack(peq[2:])])


def modo_venas(img, niv):
    """Venas: el NIR atraviesa unos milímetros de piel y la sangre lo absorbe,
    así que las venas aparecen oscuras. Aplana la iluminación y aplica contraste
    local fuerte al canal NIR. Funciona mucho mejor con luz de 850 nm y el cuarto
    a oscuras; acerca el antebrazo o el dorso de la mano."""
    r = cv2.GaussianBlur(img[:, :, 2], (0, 0), 1.2)  # sin esto el contraste fuerte realza el ruido
    detalle = r - cv2.GaussianBlur(r, (0, 0), 12)  # quita la iluminación general
    return cv2.cvtColor(_clahe_fuerte.apply(a_u8(niv("venas", detalle, fijo=(-0.15, 0.15)))),
                        cv2.COLOR_GRAY2BGR)


def separar_bandas(img):
    """Estima azul, verde, rojo e infrarrojo. El NIR entra casi por igual en los
    tres canales, así que se toma su parte común (el mínimo) como estimación.
    Es aproximado: un objeto blanco visible también tiene parte común."""
    b, g, r = cv2.split(img)
    nir = 0.8 * np.minimum(np.minimum(b, g), r)
    return {"B": b - nir, "G": g - nir, "R": r - nir, "NIR": nir}


_COLOR_COMPRIMIDO = {banda: np.array(longitud_a_bgr(comprimir(nm)), np.float32)
                     for banda, nm in CENTROS_BANDAS.items()}
# Traducción NIR: 700..1000 nm -> 400..700 nm, en 256 pasos
_LUT_TRADUCCION = np.array([longitud_a_bgr(400 + i * 300 / 255) for i in range(256)], np.float32)
_leyendas = {}


def _mostrado_comprimido(nm):
    return longitud_a_bgr(comprimir(nm))


def _mostrado_traduccion(nm):
    return longitud_a_bgr(nm - 300)


def poner_leyenda(salida, desde, hasta, color_mostrado):
    """Dibuja abajo una barra de referencia de desde..hasta nm. Arriba, el color
    real de cada longitud de onda (rayado gris = invisible); abajo, el color
    artificial con que se muestra."""
    ancho = salida.shape[1]
    clave = (ancho, desde, hasta, color_mostrado)
    if clave not in _leyendas:
        alto_barra, margen = 6, 11
        img = np.zeros((margen + 2 * alto_barra + 2, ancho, 3), np.uint8)
        for x, nm in enumerate(np.linspace(desde, hasta, ancho)):
            real = longitud_a_bgr(nm)
            if real is None:
                real = (0.35,) * 3 if (x // 3) % 2 else (0.12,) * 3
            img[margen:margen + alto_barra, x] = np.array(real) * 255
            img[margen + alto_barra + 2:, x] = np.array(color_mostrado(nm)) * 255
        for nm in np.linspace(desde, hasta, 5):
            x = int((nm - desde) / (hasta - desde) * (ancho - 1))
            cv2.putText(img, f"{nm:.0f}", (min(max(x - 8, 0), ancho - 24), 9), FUENTE, 0.3,
                        (220, 220, 220), 1, cv2.LINE_AA)
        _leyendas[clave] = img
    leyenda = _leyendas[clave]
    salida[-leyenda.shape[0]:] = leyenda


def modo_espectro_comprimido(img, niv):
    """Espectro comprimido: reparte todo lo que capta el sensor (400-1000 nm)
    dentro del visible (380-700 nm). El infrarrojo pasa a verse rojo-naranja,
    el rojo cian, el verde azul y el azul violeta. En la barra inferior, arriba
    está el color real de cada longitud de onda (rayado = IR invisible) y abajo
    cómo se muestra. La separación del IR es aproximada."""
    bandas = separar_bandas(img)
    mezcla = sum(bandas[k][:, :, None] * _COLOR_COMPRIMIDO[k] for k in bandas)
    salida = a_u8(niv("comprimido", mezcla, desde_cero=True))
    poner_leyenda(salida, *RANGO_SENSOR, _mostrado_comprimido)
    rotular_artificial(salida, "400-1000 nm en 380-700 nm")
    return salida


def rotular_artificial(salida, detalle):
    cv2.putText(salida, f"COLORES ARTIFICIALES: {detalle}", (4, 22), FUENTE, 0.33,
                (255, 255, 255), 1, cv2.LINE_AA)


def modo_traduccion_nir(img, niv):
    """Traducción NIR: desplaza el infrarrojo 700-1000 nm al visible 400-700 nm.
    El IR de 700 nm se ve violeta, el de 850 nm verde-amarillo y el de 1000 nm
    rojo. Son colores ARTIFICIALES que codifican la longitud de onda IR
    estimada; el brillo es la intensidad. Para que sea una medición, coloca un
    filtro IR 720 nm y márcalo en Ajustes: sin él, la luz visible altera los
    colores. Haz clic en la imagen para leer la longitud de onda de un punto."""
    lam, intensidad = posicion_ir(cv2.GaussianBlur(img, (3, 3), 0))
    color = _LUT_TRADUCCION[((lam - 700) / 300 * 255).astype(np.uint8)]
    salida = a_u8(color * niv("traduccion", intensidad, desde_cero=True)[:, :, None])
    poner_leyenda(salida, 700, 1000, _mostrado_traduccion)
    rotular_artificial(salida, "700-1000 nm en 400-700 nm"
                       + ("" if CONFIG["filtro_ir"] else " (sin filtro: orientativo)"))
    return salida


def parece_ir(bgr):
    """Un LED infrarrojo excita los tres filtros de color casi por igual, así que
    se ve blanco o violeta; un LED visible se ve de su color."""
    b, g, r = bgr
    m = max(b, g, r)
    return m > 0 and ((m - min(b, g, r)) / m < 0.35 or g < 0.8 * min(b, r))


class DetectorFuentesIR:
    """Fuentes IR: marca puntos de luz pequeños e intensos, como el LED de un
    control remoto o el iluminador de una cámara de seguridad, y distingue los
    que parpadean (rojo) de los fijos (amarillo). Prueba apuntando un control
    remoto a la cámara y pulsando cualquier botón."""

    admite_suavizado = False  # el promedio temporal borraría el parpadeo

    def __init__(self, umbral_brillo=0.7, umbral_cambio=0.25, area_max=0.015):
        self.umbral_brillo = umbral_brillo
        self.umbral_cambio = umbral_cambio
        self.area_max = area_max
        self.previo = None
        self.actividad = None
        self.pico = None
        self.detecciones = 0
        self._cuadros_sin_parpadeo = 99

    def __call__(self, img, niv):
        brillo = img.max(axis=2)
        alto, ancho = brillo.shape
        if self.previo is None or self.previo.shape != brillo.shape:
            self.previo = brillo
            self.actividad = np.zeros_like(brillo)
            self.pico = brillo.copy()
        # Cambio entre cuadros y brillo máximo reciente; ambos se desvanecen en
        # ~medio segundo, así un LED sigue marcado en los cuadros en que está apagado.
        self.actividad = np.maximum(self.actividad * 0.85, cv2.absdiff(brillo, self.previo))
        self.pico = np.maximum(self.pico * 0.85, brillo)
        self.previo = brillo

        candidatos = (brillo > self.umbral_brillo) | (self.actividad > self.umbral_cambio)
        candidatos = cv2.dilate(candidatos.astype(np.uint8), np.ones((3, 3), np.uint8))
        n, etiquetas, stats, centros = cv2.connectedComponentsWithStats(candidatos)

        salida = gris_a_bgr(0.6 * niv("fuentes_base", cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))
        fuentes = parpadean = 0
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area > self.area_max * brillo.size or max(w, h) > 0.12 * ancho:
                continue  # ventanas, lámparas, bordes de algo que se mueve: no son puntuales
            zona = etiquetas[y:y + h, x:x + w] == i
            if self.pico[y:y + h, x:x + w][zona].max() < 0.5:
                continue  # cambió pero no brilló: movimiento, no una fuente de luz
            parpadea = self.actividad[y:y + h, x:x + w][zona].mean() > 0.6 * self.umbral_cambio
            color = img[y:y + h, x:x + w][zona].mean(axis=0)
            fuentes += 1
            parpadean += parpadea

            cx, cy = int(centros[i][0]), int(centros[i][1])
            radio = int(max(w, h) / 2 + 6)
            tinta = (0, 0, 255) if parpadea else (0, 220, 255)
            texto = ("parpadea" if parpadea else "fija") + (" IR?" if parece_ir(color) else "")
            cv2.circle(salida, (cx, cy), radio, tinta, 1, cv2.LINE_AA)
            cv2.putText(salida, texto, (cx + radio + 2, cy + 4), FUENTE, 0.35, tinta, 1, cv2.LINE_AA)

        # Una pulsación del control = una detección, aunque el LED destelle muchas veces
        if parpadean:
            if self._cuadros_sin_parpadeo > 10:
                self.detecciones += 1
            self._cuadros_sin_parpadeo = 0
        else:
            self._cuadros_sin_parpadeo += 1
        cv2.putText(salida, f"fuentes {fuentes}  parpadeando {parpadean}  detecciones {self.detecciones}",
                    (4, alto - 18), FUENTE, 0.38, (0, 255, 0), 1, cv2.LINE_AA)
        return salida


MODOS = [
    ("Full espectro (crudo)", modo_crudo),
    ("Balance de blancos", modo_balance),
    ("Infrarrojo B/N", modo_ir),
    ("IR falso color", modo_ir_falso_color),
    ("Mapa de intensidad IR", modo_mapa_ir),
    ("Deteccion NIR", modo_deteccion),
    ("NDVI vegetacion", modo_ndvi),
    ("Canales", modo_canales),
    ("Fuentes IR", DetectorFuentesIR()),
    ("Venas NIR", modo_venas),
    ("Espectro comprimido", modo_espectro_comprimido),
    ("Traduccion NIR", modo_traduccion_nir),
]
TECLAS = "1234567890et"  # tecla de cada modo, en orden


def procesar(frame_bgr_u8, indice_modo, niv, suavizado=None):
    img = frame_bgr_u8.astype(np.float32) / 255.0
    funcion = MODOS[indice_modo][1]
    if suavizado is not None and getattr(funcion, "admite_suavizado", True):
        img = suavizado(img)
    return funcion(img, niv)
