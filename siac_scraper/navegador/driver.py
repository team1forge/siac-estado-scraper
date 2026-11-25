"""Crear el navegador y manejar sus ventanas.

SIAC abre muchas ventanas (popups de productos, de clientes, alertas, detalle de líneas) y
las cierra solas a veces. Estas funciones toleran que una ventana desaparezca mientras se
la consulta.
"""
from __future__ import annotations

import logging
import time

from selenium.common.exceptions import UnexpectedAlertPresentException

from siac_scraper.config import Navegador

log = logging.getLogger(__name__)


class NavegadorCerrado(RuntimeError):
    """El navegador (o su driver) se cerró a mitad del trabajo.

    No es un error del RUC que se estaba consultando: el robot la atrapa, abre un navegador
    nuevo y retoma desde el último RUC guardado en el CSV.
    """


def crear_driver(cfg: Navegador):
    """Abre Chrome o Edge con las opciones que necesita el portal.

    Selenium Manager (incluido en Selenium 4.6+) descarga el driver que corresponda a la
    versión instalada del navegador.

    Parámetros:
        cfg: la sección ``Navegador`` de la configuración.

    Devuelve:
        El ``WebDriver`` ya abierto, sin ninguna página cargada.
    """
    from selenium import webdriver

    edge = cfg.nombre == "edge"
    opts = webdriver.EdgeOptions() if edge else webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    # 'none': get() vuelve enseguida en vez de esperar la carga. Hace falta porque la ventana
    # de autenticación de Windows bloquea la carga, y hay que llenarla mientras tanto.
    opts.set_capability("pageLoadStrategy", "none")
    if cfg.auth_allowlist:
        # Autenticación integrada de Windows: el navegador responde solo al reto NTLM/Kerberos
        opts.add_argument(f"--auth-server-allowlist={cfg.auth_allowlist}")
        opts.add_argument(f"--auth-negotiate-delegate-allowlist={cfg.auth_allowlist}")
    if cfg.perfil is not None:
        cfg.perfil.mkdir(parents=True, exist_ok=True)
        opts.add_argument(f"--user-data-dir={cfg.perfil}")
    if cfg.mantener_abierto:
        # sin 'detach' el navegador se cierra al terminar el proceso de Python
        opts.add_experimental_option("detach", True)
    return webdriver.Edge(options=opts) if edge else webdriver.Chrome(options=opts)


def driver_vivo(driver):
    """True si el navegador sigue abierto y responde. Nunca lanza excepción."""
    if driver is None:
        return False
    try:
        return bool(driver.window_handles)
    except UnexpectedAlertPresentException:
        return True                           # hay un alert() abierto, pero el navegador vive
    except Exception:
        return False                          # sesión inválida, driver muerto, sin ventanas...


def esperar_carga(driver, timeout):
    """Espera a que la ventana actual termine de cargar (``document.readyState == complete``).

    Devuelve:
        True si cargó; False si se agotó el tiempo o la ventana se cerró (no lanza excepción).
    """
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            if driver.execute_script("return document.readyState") == "complete":
                return True
        except Exception:
            return False
        time.sleep(0.5)
    return False


def ventanas_vivas(driver):
    """Recorre las ventanas abiertas y devuelve ``[(handle, título, url), ...]`` de las que
    responden. Deja el driver en la última ventana recorrida."""
    vivas = []
    for h in driver.window_handles:
        try:
            driver.switch_to.window(h)
            vivas.append((h, driver.title or "", driver.current_url or ""))
        except Exception:
            continue                          # se cerró mientras la consultaba
    return vivas


def aceptar_alerta_nativa(driver):
    """Si hay un ``alert()`` de JavaScript abierto, lo acepta.

    Mientras un alert() está abierto Selenium no puede hacer nada más en esa ventana, así
    que se llama antes de cada paso delicado.

    Devuelve:
        El texto del alert, o None si no había ninguno.
    """
    try:
        alerta = driver.switch_to.alert
        texto = alerta.text or "Alerta"
        alerta.accept()
        return texto
    except Exception:
        return None


def nuevas_ventanas(driver, antes):
    """Handles de las ventanas que no estaban en ``antes`` (las que se abrieron después)."""
    return [h for h in driver.window_handles if h not in antes]
