"""Contraseñas en el Administrador de credenciales de Windows (a través de ``keyring``).

La contraseña nunca va en el código ni en archivos del proyecto. Por defecto el portal usa la
misma contraseña que la VPN, guardada bajo el servicio ``ivanti_vpn``; si el portal usa otra,
se guarda aparte bajo ``portal_distribuidores`` (ver ``Credenciales.reusar_vpn``).
"""
from __future__ import annotations

import getpass

from siac_scraper.config import Credenciales


def _ubicacion(cfg: Credenciales, portal: bool):
    """(servicio, usuario) bajo los que keyring guarda la contraseña que se necesita."""
    if portal and not cfg.reusar_vpn:
        return cfg.servicio_keyring_portal, cfg.usuario_del_portal
    return cfg.servicio_keyring, cfg.usuario


def password_portal(cfg: Credenciales):
    """Credenciales para entrar al portal y a SIAC.

    Devuelve:
        ``(usuario, contraseña)``.

    Lanza:
        RuntimeError: si no hay contraseña guardada (dice qué comando ejecutar).
    """
    import keyring

    servicio, usuario_keyring = _ubicacion(cfg, portal=True)
    pwd = keyring.get_password(servicio, usuario_keyring)
    if not pwd:
        opcion = "" if cfg.reusar_vpn else " --portal"
        raise RuntimeError("No hay contraseña guardada. Ejecuta: "
                           f"python -m siac_scraper guardar-password{opcion}")
    return cfg.usuario_del_portal, pwd


def guardar_password(cfg: Credenciales, portal=False):
    """Pide la contraseña por consola (sin mostrarla) y la guarda en el Administrador de credenciales.

    Parámetros:
        cfg: la sección ``Credenciales`` de la configuración.
        portal: True para guardar la contraseña aparte del portal; False para la de la VPN.

    Devuelve:
        True si se guardó; False si se dejó vacía.
    """
    import keyring

    servicio, usuario = (cfg.servicio_keyring_portal, cfg.usuario_del_portal) if portal \
        else (cfg.servicio_keyring, cfg.usuario)
    pwd = getpass.getpass(f"Contraseña para {usuario} (no se mostrará): ")
    if not pwd:
        print("Contraseña vacía; no se guardó nada.")
        return False
    keyring.set_password(servicio, usuario, pwd)
    print("Guardada en el Administrador de credenciales de Windows.")
    if portal and cfg.reusar_vpn:
        print("Ojo: Credenciales.reusar_vpn está en True, así que el portal seguirá usando la "
              "contraseña de la VPN. Ponlo en False en config.py para usar esta.")
    return True


def verificar_password(cfg: Credenciales, url):
    """Diagnóstico: qué autenticación pide el portal y si la contraseña guardada funciona.

    Hace peticiones HTTP directas (sin navegador). Si el portal usa NTLM, prueba el usuario
    en tres formatos (tal cual, ``TIM\\usuario`` y ``usuario@tim.com.pe``) e informa cuál
    aceptó, para ponerlo en ``Credenciales.usuario_portal``.

    Parámetros:
        cfg: la sección ``Credenciales`` de la configuración.
        url: dirección del portal.

    Devuelve:
        True si alguna variante fue aceptada.
    """
    import keyring

    guardada = keyring.get_password(cfg.servicio_keyring, cfg.usuario)
    if not guardada:
        print(f"No hay contraseña guardada para {cfg.usuario}.")
        print("Ejecuta: python -m siac_scraper guardar-password")
        return False
    # solo la primera y la última letra, para confirmar que es la que se espera
    print(f"Guardada para {cfg.usuario}: {guardada[0]}{'*' * (len(guardada) - 2)}{guardada[-1]}"
          f"  ({len(guardada)} caracteres)")

    try:
        import requests
        from requests.auth import HTTPBasicAuth
    except ImportError:
        print("Instala requests: pip install requests")
        return False

    # 1) Sin credenciales: el servidor responde 401 diciendo qué esquema acepta
    try:
        r = requests.get(url, timeout=20)
    except Exception as e:
        print(f"No se pudo conectar ({e}). ¿Está la VPN arriba?")
        return False
    esquemas = r.headers.get("WWW-Authenticate", "")
    print(f"El portal responde {r.status_code}; esquemas que pide: {esquemas or '(ninguno)'}")
    usa_ntlm = "ntlm" in esquemas.lower() or "negotiate" in esquemas.lower()

    # 2) Probar las credenciales con ese esquema
    intentos = []
    if usa_ntlm:
        print("=> Usa NTLM/Negotiate, no Basic.")
        try:
            from requests_ntlm import HttpNtlmAuth
        except ImportError:
            print("Para probar NTLM: pip install requests-ntlm")
            return False
        for usr in (cfg.usuario_del_portal, f"TIM\\{cfg.usuario}", f"{cfg.usuario}@tim.com.pe"):
            intentos.append((usr, HttpNtlmAuth(usr, guardada)))
    else:
        intentos.append((cfg.usuario_del_portal, HTTPBasicAuth(cfg.usuario_del_portal, guardada)))

    for usr, auth in intentos:
        try:
            r = requests.get(url, auth=auth, timeout=30)
        except Exception as e:
            print(f"  {usr}: error ({e})")
            continue
        if r.status_code < 400:
            print(f"  {usr}: ACEPTADO ({r.status_code}). Usa este valor en Credenciales.usuario_portal.")
            return True
        print(f"  {usr}: rechazado ({r.status_code})")

    print("Ninguna variante funcionó. Puede ser un dominio distinto al que asumí ('TIM').")
    return False
