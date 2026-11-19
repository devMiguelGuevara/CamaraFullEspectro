"""Detecta cámaras: USB conectados (aunque Windows no tenga driver para ellos),
dispositivos de imagen registrados en Windows e índices usables por OpenCV."""
import json
import os
import re
import subprocess

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import usb1
except ImportError:
    usb1 = None

# Webcams con chip PixArt PAC207 (tabla de IDs del driver Linux gspca/pac207.c).
PAC207_IDS = {
    (0x041E, 0x4028), (0x093A, 0x2460), (0x093A, 0x2461), (0x093A, 0x2463),
    (0x093A, 0x2464), (0x093A, 0x2468), (0x093A, 0x2470), (0x093A, 0x2471),
    (0x093A, 0x2472), (0x093A, 0x2474), (0x093A, 0x2476), (0x145F, 0x013A),
    (0x2001, 0xF115),
}
NOMBRES = {(0x2001, 0xF115): "D-Link DSB-C120"}

VELOCIDADES = {1: "low-speed", 2: "full-speed (USB 1.1)", 3: "high-speed (USB 2.0)",
               4: "super-speed (USB 3)", 5: "super-speed+"}


def camara_conocida(vid, pid):
    if (vid, pid) in PAC207_IDS:
        nombre = NOMBRES.get((vid, pid), "Webcam")
        return f"{nombre} (chip PixArt PAC207, en Linux: gspca_pac207)"
    return None


def powershell_json(comando):
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", comando + " | ConvertTo-Json"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except Exception:
        return []
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def usb_windows():
    """Todos los USB que Windows ha visto alguna vez (conectados o no), con su driver."""
    devs = powershell_json(
        "Get-PnpDevice | Where-Object { $_.InstanceId -like 'USB\\VID_*' } | "
        "Select-Object FriendlyName, Class, Status, Present, Service, InstanceId"
    )
    for d in devs:
        m = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", d["InstanceId"], re.I)
        d["vidpid"] = (int(m.group(1), 16), int(m.group(2), 16)) if m else None
        d["interfaz"] = "&MI_" in d["InstanceId"].upper()
    return devs


def camaras_windows():
    """Dispositivos de imagen/cámara que Windows reconoce como tales."""
    return powershell_json(
        "Get-PnpDevice -PresentOnly | "
        "Where-Object { $_.Class -in 'Camera','Image' } | "
        "Select-Object FriendlyName, Status, InstanceId"
    )


def pista_por_descriptores(dev):
    """Adivina si un USB es cámara mirando sus interfaces."""
    try:
        for cfg in dev.iterConfigurations():
            for intf in cfg:
                for s in intf:
                    if s.getClass() == 0x0E:
                        return "cámara UVC (estándar)"
                    iso_in = any((ep.getAttributes() & 3) == 1 and ep.getAddress() & 0x80
                                 for ep in s)
                    if s.getClass() == 0xFF and iso_in:
                        return "posible cámara propietaria (clase de fabricante + endpoint isócrono)"
    except usb1.USBError:
        pass
    return ""


def usb_conectados():
    """USB conectados según libusb, que lee los descriptores sin necesitar driver."""
    res = []
    with usb1.USBContext() as ctx:
        for dev in ctx.getDeviceList(skip_on_error=True):
            res.append({
                "vidpid": (dev.getVendorID(), dev.getProductID()),
                "bus": dev.getBusNumber(),
                "dir": dev.getDeviceAddress(),
                "velocidad": VELOCIDADES.get(dev.getDeviceSpeed(), "?"),
                "pista": pista_por_descriptores(dev),
            })
    return res


def nombres_dshow():
    """Nombres de las cámaras DirectShow, en el mismo orden que los índices de
    OpenCV con CAP_DSHOW. Usa ffmpeg; devuelve [] si no está instalado."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        ).stderr
    except (OSError, subprocess.TimeoutExpired):
        return []
    return re.findall(r'"([^"]+)" \(video\)', out)


def camaras_opencv(max_indices=10):
    """Prueba índices 0..max_indices-1 y devuelve los que entregan imagen."""
    encontradas = []
    for i in range(max_indices):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                fps = cap.get(cv2.CAP_PROP_FPS)
                encontradas.append((i, w, h, fps))
        cap.release()
    return encontradas


def main():
    win = usb_windows()
    win_nodos = [d for d in win if d["vidpid"] and not d["interfaz"]]

    print("=== USB conectados (libusb) ===")
    if usb1 is None:
        print("libusb no instalado: pip install libusb1")
        conectados = set()
    else:
        usb = usb_conectados()
        conectados = {u["vidpid"] for u in usb}
        for u in usb:
            vid, pid = u["vidpid"]
            w = next((d for d in win_nodos if d["vidpid"] == u["vidpid"] and d["Present"]), None)
            nombre = w["FriendlyName"] if w else "(hub / sin nodo en Windows)"
            driver = (w["Service"] or "SIN DRIVER") if w else "-"
            conocida = camara_conocida(vid, pid)
            marca = "*" if conocida or u["pista"] else " "
            print(f"{marca} {vid:04x}:{pid:04x}  bus {u['bus']} dir {u['dir']:<3} "
                  f"{u['velocidad']:<21} driver: {driver:<12} {nombre}")
            for extra in (conocida, u["pista"]):
                if extra:
                    print(f"      -> {extra}")

    print("\n=== Cámaras conocidas registradas en Windows pero desconectadas ===")
    vistas = {d["vidpid"]: d for d in win_nodos if camara_conocida(*d["vidpid"])}
    desconectadas = [d for vp, d in vistas.items() if vp not in conectados]
    if desconectadas:
        for d in desconectadas:
            vid, pid = d["vidpid"]
            print(f"- {vid:04x}:{pid:04x}  {camara_conocida(vid, pid)}")
            print(f"    Windows la llamó '{d['FriendlyName']}'. Conéctala y vuelve a ejecutar.")
    else:
        print("(ninguna)")

    print("\n=== Dispositivos de cámara en Windows ===")
    devs = camaras_windows()
    if devs:
        for d in devs:
            print(f"- {d['FriendlyName']}  [{d['Status']}]")
            print(f"    {d['InstanceId']}")
    else:
        print("(ninguno encontrado)")

    print("\n=== Índices utilizables con OpenCV ===")
    if cv2 is None:
        print("OpenCV no instalado: pip install opencv-python")
        return
    cams = camaras_opencv()
    nombres = nombres_dshow()
    if cams:
        for i, w, h, fps in cams:
            fps_txt = f"{fps:.0f} fps" if fps > 0 else "fps desconocido"
            nombre = nombres[i] if i < len(nombres) else ""
            print(f"- Índice {i}: {w}x{h} ({fps_txt})  {nombre}")
    else:
        print("(ninguna cámara respondió)")


if __name__ == "__main__":
    main()
