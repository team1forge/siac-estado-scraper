"""Barra de búsqueda de SIAC Único: tipo de búsqueda, caja de texto y lupa.

La barra tiene un desplegable con el tipo de búsqueda (Teléfono, Documento Identidad...), una
caja de texto y un botón con una lupa. Al buscar, SIAC abre el popup "Consulta de Productos"
(eso lo atiende ``popups.py``).
"""
from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from siac_scraper.navegador.dom import (centrar, clic, compacta, es_visible, normaliza,
                                        primero_visible, visibles, xpath_texto)
from siac_scraper.siac.selectores import OPCIONES_BUSQUEDA

log = logging.getLogger(__name__)

_XPATH_DESPLEGABLES = "//*[contains(@class,'dropdown-toggle')] | //*[@data-toggle='dropdown']"
# Formas en que SIAC puede dibujar la lupa, de la más específica a la más genérica
_XPATH_LUPA = ("//button[contains(@class,'search')]", "//*[contains(@class,'glyphicon-search')]/..",
               "//*[contains(@class,'fa-search')]/..", "//button[@type='submit']")
ESPERA_TRAS_BUSCAR = 3        # segundos tras presionar la lupa, antes de buscar el popup


def _texto_corto(el, maximo=25):
    """True si el elemento tiene texto y es corto (un botón, no un párrafo)."""
    try:
        return 0 < len(el.text.strip()) < maximo
    except Exception:
        return False


def buscar_desplegable(driver):
    """El botón del desplegable de tipo de búsqueda, o None.

    Hay otros desplegables en la página (por ejemplo, el menú del usuario), así que se
    prueban tres criterios, del más seguro al más laxo.
    """
    # 1) Un botón/desplegable cuyo texto ES un tipo de búsqueda. En la ficha del cliente hay
    #    muchos textos con "Cuenta"; exigir el texto completo evita confundir una etiqueta.
    opciones = {normaliza(o) for o in OPCIONES_BUSQUEDA}
    for el in driver.find_elements(By.XPATH, "//button | " + _XPATH_DESPLEGABLES):
        try:
            if el.is_displayed() and normaliza(compacta(el.text)) in opciones:
                return el
        except Exception:
            continue
    # 2) Cualquier elemento corto que muestre un tipo de búsqueda
    for opcion in OPCIONES_BUSQUEDA:
        for el in driver.find_elements(By.XPATH, xpath_texto(("button", "a", "span", "div"), opcion)):
            if es_visible(el) and _texto_corto(el):
                return el
    # 3) Respaldo: un desplegable visible con texto corto
    for el in driver.find_elements(By.XPATH, _XPATH_DESPLEGABLES):
        if es_visible(el) and _texto_corto(el):
            return el
    return None


def seleccionar_tipo_busqueda(driver, texto):
    """Abre el desplegable de tipo de búsqueda y elige una opción.

    Parámetros:
        texto: la opción a elegir, ej. "Documento Identidad".

    Devuelve:
        El elemento de la opción clicada.

    Lanza:
        RuntimeError: si no encuentra el desplegable o la opción (el mensaje lista las
        opciones visibles).
    """
    toggle = buscar_desplegable(driver)
    if toggle is None:
        raise RuntimeError("No encontré el desplegable de tipo de búsqueda en SIAC.")

    actual = toggle.text.strip()
    log.info("SIAC: desplegable %r; lo abro para elegir %r...", actual, texto)
    centrar(driver, toggle)
    time.sleep(0.5)
    clic(driver, toggle)
    time.sleep(1.5)                           # animación de apertura del menú

    # la opción solo es visible con el menú abierto
    opcion = primero_visible(driver.find_elements(By.XPATH, xpath_texto(("a", "li", "span", "button"), texto)))
    if opcion is None:
        visibles_ = sorted({el.text.strip() for el in visibles(driver.find_elements(By.XPATH, "//li | //a"))
                            if el.text.strip() and len(el.text.strip()) < 40})[:30]
        raise RuntimeError(f"Abrí el desplegable pero no encontré '{texto}'. "
                           f"Opciones visibles: {', '.join(visibles_)}")

    clic(driver, opcion)
    time.sleep(1)
    # se comprueba releyendo el botón: si no cambió, la búsqueda usaría el tipo equivocado
    toggle = buscar_desplegable(driver)
    nuevo = toggle.text.strip() if toggle is not None else ""
    if normaliza(texto) in normaliza(nuevo):
        log.info("SIAC: tipo de búsqueda %r -> %r", actual, nuevo)
    else:
        log.warning("SIAC: el desplegable sigue mostrando %r; puede que el clic no aplicara.", nuevo)
    return opcion


def buscar(driver, valor):
    """Escribe el valor en la caja de búsqueda y presiona la lupa (o ENTER si no la encuentra).

    No espera el resultado: después de ``ESPERA_TRAS_BUSCAR`` segundos vuelve, y el popup
    que abra SIAC lo detecta ``popups.esperar_popup``.

    Lanza:
        RuntimeError: si no hay ninguna caja de texto visible.
    """
    # la caja es el primer input de texto visible y habilitado de la página
    caja = None
    for el in driver.find_elements(By.XPATH, "//input[@type='text'] | //input[not(@type)]"):
        try:
            if el.is_displayed() and el.is_enabled():
                caja = el
                break
        except Exception:
            continue
    if caja is None:
        raise RuntimeError("No encontré la caja de búsqueda en SIAC.")

    caja.clear()
    caja.send_keys(valor)
    time.sleep(0.5)
    escrito = caja.get_attribute("value")
    if escrito != valor:
        log.warning("SIAC: la caja quedó con %r en vez de %r", escrito, valor)

    # el primer xpath de _XPATH_LUPA que encuentre algo visible
    lupa = next((v[0] for v in (visibles(driver.find_elements(By.XPATH, xp)) for xp in _XPATH_LUPA) if v), None)
    if lupa is not None:
        como = clic(driver, lupa)
        log.info("SIAC: buscando %r (lupa, clic %s).", valor, como)
    else:
        caja.send_keys(Keys.ENTER)
        log.info("SIAC: buscando %r (no ubiqué la lupa; ENTER en la caja).", valor)

    time.sleep(ESPERA_TRAS_BUSCAR)
    return True
