"""Estado eléctrico de cada puerto de los hubs raíz USB (como USBView de Microsoft).
Distingue un puerto vacío de uno con un dispositivo que falla al enumerarse."""
import ctypes
import json
import subprocess
from ctypes import wintypes

GUID_HUB = "{f18a0e88-c30c-11d0-8815-00a0c906bed8}"
IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX = 0x220448
IOCTL_USB_GET_PORT_CONNECTOR_PROPERTIES = 0x220454
IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2 = 0x22045C
ESTADOS = {
    0: "vacío", 1: "CONECTADO", 2: "FALLÓ LA ENUMERACIÓN", 3: "fallo general",
    4: "SOBRECORRIENTE", 5: "energía insuficiente", 6: "ancho de banda insuficiente",
    7: "hubs demasiado anidados", 8: "en hub antiguo", 9: "enumerando...", 10: "reiniciándose",
}
VELOCIDADES = {0: "low", 1: "full", 2: "high", 3: "super"}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                wintypes.LPVOID]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
INVALID_HANDLE = wintypes.HANDLE(-1).value


def hubs_raiz():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\\ROOT_HUB*' } | "
         "Select-Object -ExpandProperty InstanceId | ConvertTo-Json"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    ids = json.loads(out) if out else []
    return [ids] if isinstance(ids, str) else ids


def ioctl(h, codigo, entrada):
    """DeviceIoControl con un buffer de 512 bytes; devuelve los bytes o None si falla."""
    buf = ctypes.create_string_buffer(entrada, 512)
    n = wintypes.DWORD()
    if not k32.DeviceIoControl(h, codigo, buf, 512, buf, 512, ctypes.byref(n), None):
        return None
    return buf.raw


def u32(*valores):
    return b"".join(v.to_bytes(4, "little") for v in valores)


def puertos(instance_id):
    ruta = "\\\\?\\" + instance_id.replace("\\", "#") + "#" + GUID_HUB
    h = k32.CreateFileW(ruta, 0x40000000, 0x2, None, 3, 0, None)  # GENERIC_WRITE, FILE_SHARE_WRITE
    if h == INVALID_HANDLE:
        raise OSError(ctypes.get_last_error(), f"No se pudo abrir {ruta}")
    try:
        for puerto in range(1, 32):
            b = ioctl(h, IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX, u32(puerto))
            if b is None:
                break  # no hay más puertos
            # Estructuras empaquetadas a 1 byte (usbioctl.h)
            info = {
                "puerto": puerto,
                "vid": int.from_bytes(b[12:14], "little"),
                "pid": int.from_bytes(b[14:16], "little"),
                "velocidad": VELOCIDADES.get(b[23], "?"),
                "estado": int.from_bytes(b[31:35], "little"),
                "protocolos": "",
                "usuario": None,
            }
            v2 = ioctl(h, IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2, u32(puerto, 16, 0x7))
            if v2:
                bits = int.from_bytes(v2[8:12], "little")
                info["protocolos"] = "/".join(n for i, n in enumerate(("1.1", "2.0", "3.x"))
                                              if bits >> i & 1)
            cp = ioctl(h, IOCTL_USB_GET_PORT_CONNECTOR_PROPERTIES, u32(puerto, 0))
            if cp:
                info["usuario"] = bool(int.from_bytes(cp[8:12], "little") & 1)
                info["compañero"] = int.from_bytes(cp[14:16], "little")
            yield info
    finally:
        k32.CloseHandle(h)


def main():
    for hub in hubs_raiz():
        print(f"Hub raíz {hub}")
        for p in puertos(hub):
            estado = ESTADOS.get(p["estado"], f"estado {p['estado']}")
            acceso = {True: "externo", False: "interno", None: "?"}[p["usuario"]]
            companero = f" par={p['compañero']}" if p.get("compañero") else ""
            linea = f"  puerto {p['puerto']:>2} [USB {p['protocolos'] or '?':<7} {acceso}{companero}]: {estado}"
            if p["estado"] != 0:
                linea += f"  {p['vid']:04x}:{p['pid']:04x} ({p['velocidad']}-speed)"
            print(linea)


if __name__ == "__main__":
    main()
