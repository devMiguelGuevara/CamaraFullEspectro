"""Consulta un dispositivo USB a bajo nivel con libusb: muestra sus descriptores y,
si es una webcam PAC207 (D-Link DSB-C120), lee el ID del chip para comprobar
que responde.

Uso:
    python consultar_usb.py              # D-Link DSB-C120 (2001:f115)
    python consultar_usb.py 093a:2521    # cualquier otro VID:PID
    python consultar_usb.py --led        # además enciende el LED 2 s (solo PAC207)

Leer descriptores funciona sin driver. Para hablarle al chip hay que asociarle el
driver genérico libusbK con Zadig (https://zadig.akeo.ie). WinUSB no sirve para
la PAC207: fuerza el byte bajo de wIndex al número de interfaz, y el chip usa
wIndex como número de registro.
"""
import argparse
import sys
import time

import usb1

from detectar_camaras import PAC207_IDS, VELOCIDADES, camara_conocida, usb_windows

CLASES = {0x00: "definida por interfaz", 0x01: "audio", 0x03: "HID",
          0x08: "almacenamiento", 0x09: "hub", 0x0E: "video (UVC)",
          0xE0: "inalámbrico", 0xEF: "misceláneo", 0xFF: "del fabricante"}
TIPOS_EP = {0: "control", 1: "isócrono", 2: "bulk", 3: "interrupción"}

# Peticiones de fabricante dirigidas a la interfaz, igual que pac207.c
PAC207_IN = usb1.ENDPOINT_IN | usb1.TYPE_VENDOR | usb1.RECIPIENT_INTERFACE
PAC207_OUT = usb1.ENDPOINT_OUT | usb1.TYPE_VENDOR | usb1.RECIPIENT_INTERFACE


def mostrar_descriptores(dev):
    vid, pid = dev.getVendorID(), dev.getProductID()
    bcd = dev.getbcdUSB()
    print(f"Dispositivo {vid:04x}:{pid:04x}  bus {dev.getBusNumber()} "
          f"dirección {dev.getDeviceAddress()}  puerto {dev.getPortNumberList()}")
    print(f"  USB {bcd >> 8}.{(bcd >> 4) & 0xF}, {VELOCIDADES.get(dev.getDeviceSpeed(), '?')}, "
          f"clase {dev.getDeviceClass():#04x} ({CLASES.get(dev.getDeviceClass(), '?')}), "
          f"EP0 {dev.getMaxPacketSize0()} bytes")
    for cfg in dev.iterConfigurations():
        unidad = 8 if dev.getDeviceSpeed() >= usb1.SPEED_SUPER else 2
        print(f"  Configuración {cfg.getConfigurationValue()}: {cfg.getNumInterfaces()} "
              f"interfaz(es), consumo máx. {cfg.getMaxPower() * unidad} mA")
        for intf in cfg:
            for s in intf:
                print(f"    Interfaz {s.getNumber()} alt {s.getAlternateSetting()}: "
                      f"clase {s.getClass():#04x} ({CLASES.get(s.getClass(), '?')}), "
                      f"{s.getNumEndpoints()} endpoint(s)")
                for ep in s:
                    addr = ep.getAddress()
                    print(f"      EP {addr:#04x} {'IN ' if addr & 0x80 else 'OUT'} "
                          f"{TIPOS_EP[ep.getAttributes() & 3]:<12} "
                          f"{ep.getMaxPacketSize() & 0x7FF:>4} bytes, intervalo {ep.getInterval()}")


def driver_windows(vidpid):
    for d in usb_windows():
        if d["vidpid"] == vidpid and d["Present"] and not d["interfaz"]:
            return d["Service"] or "SIN DRIVER"
    return "?"


def mostrar_textos(dev):
    for etiqueta, leer in (("Fabricante", dev.getManufacturer),
                           ("Producto", dev.getProduct),
                           ("Nº serie", dev.getSerialNumber)):
        try:
            print(f"  {etiqueta}: {leer()}")
        except usb1.USBError:
            pass


def pac207_leer(handle, reg):
    return handle.controlRead(PAC207_IN, 0x00, 0x00, reg, 1, timeout=100)[0]


def pac207_escribir(handle, reg, valor):
    handle.controlWrite(PAC207_OUT, 0x00, valor, reg, b"", timeout=100)


def consultar_pac207(handle, led):
    handle.claimInterface(0)
    try:
        r0, r1 = pac207_leer(handle, 0x0000), pac207_leer(handle, 0x0001)
        sensor = ((r0 & 0x0F) << 4) | (r1 >> 4)
        print(f"\nRegistros 0x00=0x{r0:02x} 0x01=0x{r1:02x} -> "
              f"sensor ID 0x{sensor:02x}, chip ID 0x{r1 & 0x0F:02x}")
        if sensor == 0x27:
            print("OK: el chip PixArt PAC207BCA responde. La comunicación funciona.")
        else:
            print("ID inesperado (se esperaba sensor 0x27). Si el driver es WinUSB, "
                  "cámbialo por libusbK en Zadig.")
        if led:
            print("Encendiendo el LED 2 segundos...")
            pac207_escribir(handle, 0x41, 0x02)  # registro de modo, bit 1 = LED
            time.sleep(2)
            pac207_escribir(handle, 0x41, 0x00)
    finally:
        handle.releaseInterface(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("vidpid", nargs="?", default="2001:f115", help="VID:PID en hexadecimal")
    ap.add_argument("--led", action="store_true", help="enciende el LED 2 s (solo PAC207)")
    args = ap.parse_args()
    vid, pid = (int(x, 16) for x in args.vidpid.split(":"))

    with usb1.USBContext() as ctx:
        dev = ctx.getByVendorIDAndProductID(vid, pid, skip_on_error=True)
        if dev is None:
            print(f"{vid:04x}:{pid:04x} no está en el bus USB. ¿Está conectado? "
                  "Prueba otro puerto (mejor uno trasero, directo a la placa) "
                  "y ejecuta detectar_camaras.py.")
            sys.exit(1)

        if camara_conocida(vid, pid):
            print(camara_conocida(vid, pid))
        mostrar_descriptores(dev)
        driver = driver_windows((vid, pid))
        print(f"  Driver en Windows: {driver}")

        try:
            handle = dev.open()
        except usb1.USBError as e:
            print(f"\nNo se pudo abrir el dispositivo ({e}).")
            print("Windows no le tiene asociado un driver que libusb pueda usar.")
            print("Instala libusbK con Zadig: Options > List All Devices, elige el "
                  "dispositivo, selecciona 'libusbK' y pulsa 'Install Driver'.")
            sys.exit(2)

        try:
            mostrar_textos(dev)
            if (vid, pid) in PAC207_IDS:
                if driver.lower() == "winusb":
                    print("\nAviso: con WinUSB solo se puede leer el registro 0; usa libusbK.")
                consultar_pac207(handle, args.led)
        finally:
            handle.close()


if __name__ == "__main__":
    main()
