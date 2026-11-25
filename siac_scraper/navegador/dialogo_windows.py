"""Teclea usuario y contraseña en la ventana de autenticación de Windows (solo Windows).

Cuando el portal o SIAC piden credenciales, aparece una ventana del sistema operativo, no de
la página. Selenium no la ve, así que se usa pywinauto: se le da el foco al navegador y se
escriben las teclas como si fuera una persona.

pywinauto se importa dentro de cada función para que el resto del paquete (y las pruebas)
funcione en macOS y Linux.
"""
from __future__ import annotations

import time

# Caracteres con significado especial para send_keys (Shift, Ctrl, Alt, Enter, agrupaciones)
_ESPECIALES = "+^%~(){}[]"


def escapar_teclas(texto):
    """Escapa los caracteres especiales de send_keys para que se escriban tal cual.

    Ejemplo: ``"a+b"`` -> ``"a{+}b"`` (sin escapar, ``+`` significaría Shift).
    """
    return "".join("{%s}" % c if c in _ESPECIALES else c for c in texto)


def ventana_navegador(nombre_navegador):
    """Busca la ventana visible de Chrome o Edge en el escritorio.

    Parámetros:
        nombre_navegador: "chrome" o "edge".

    Devuelve:
        La ventana de pywinauto, o None si no está.
    """
    from pywinauto import Desktop

    marca = "Edge" if nombre_navegador == "edge" else "Chrome"
    for w in Desktop(backend="uia").windows():
        try:
            # Chrome_WidgetWin_1 es la clase de ventana de todos los navegadores Chromium
            if (w.class_name() == "Chrome_WidgetWin_1" and w.is_visible()
                    and marca in (w.window_text() or "")):
                return w
        except Exception:
            continue                          # la ventana se cerró mientras la revisaba
    return None


def teclear(ventana, usuario, password, pausa_tecla, espera_foco):
    """Escribe usuario, TAB, contraseña y ENTER en la ventana de autenticación.

    Se escribe letra por letra con pausas porque, si se envía todo de golpe, la ventana de
    Windows pierde caracteres y la contraseña queda incompleta.

    Parámetros:
        ventana: la ventana del navegador (de ``ventana_navegador``).
        usuario, password: credenciales a escribir.
        pausa_tecla: segundos entre tecla y tecla.
        espera_foco: segundos de espera tras dar el foco, antes de empezar a escribir.
    """
    from pywinauto.keyboard import send_keys

    ventana.set_focus()
    time.sleep(espera_foco)                   # el diálogo tarda en tomar el foco
    for ch in usuario:
        send_keys(escapar_teclas(ch))
        time.sleep(pausa_tecla)
    time.sleep(1)
    send_keys("{TAB}")                        # pasa al campo de la contraseña
    time.sleep(1)
    for ch in password:
        send_keys(escapar_teclas(ch))
        time.sleep(pausa_tecla)
    time.sleep(1)
    send_keys("{ENTER}")
