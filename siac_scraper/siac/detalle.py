"""Del popup de productos a la ficha del cliente.

SIAC no muestra los datos del cliente (razón social, contacto, correo...) en el popup de
productos. Para llegar a ellos hay que dar dos clics:

1. Elegir una fila con líneas (preferiblemente no HFC/FTTH) y clicar su "Total Activas"
   (o "Total No Activas") -> se abre el detalle "Líneas asociadas".
2. Clicar el primer número de línea del detalle -> la ventana de SIAC pasa a mostrar la
   ficha de ese cliente (la lee ``ficha.py``).

El recuadro del total no siempre responde al primer tipo de clic, por eso ``clic_total``
prueba varias formas, una tras otra.
"""
from __future__ import annotations

import logging
import re
import time
from typing import NamedTuple, Optional
from urllib.parse import unquote

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from siac_scraper.navegador.dom import centrar, clic, texto_visible
from siac_scraper.navegador.driver import aceptar_alerta_nativa, esperar_carga
from siac_scraper.siac import selectores
from siac_scraper.siac.tablas import (describir_tablas, esperar_primera_fila, indice_activas,
                                      indice_no_activas, tablas_servicios)

log = logging.getLogger(__name__)

# Qué recuadro de la fila se clica
ACTIVAS, NO_ACTIVAS = "activas", "no_activas"


class Eleccion(NamedTuple):
    """El recuadro que se va a clicar en la tabla de productos."""

    fila: int            # índice de la fila (0 = primera)
    clave: str           # ACTIVAS o NO_ACTIVAS
    valor: int           # cuántas líneas tiene ese recuadro


# ------------------------- qué fila clicar -------------------------
def elegir_fila(totales) -> Optional[Eleccion]:
    """Decide qué recuadro clicar para abrir el detalle de líneas.

    Regla: la primera fila con Total Activas >= 1; si no tiene, su Total No Activas >= 1;
    si tiene 0 y 0, la fila siguiente. Las filas de productos fijos (HFC, FTTH) se saltan
    porque su detalle suele fallar, y solo se usan si ninguna otra fila tiene líneas.

    Parámetros:
        totales: ``[(producto, activas, no_activas), ...]`` de ``esperar_primera_fila``.

    Devuelve:
        La ``Eleccion``, o None si ninguna fila tiene líneas.
    """
    def recorrer(evitar_fijos):
        """La primera fila con líneas; con ``evitar_fijos`` se saltan las HFC/FTTH."""
        for n, (producto, activas, no_activas) in enumerate(totales):
            if evitar_fijos and selectores.PRODUCTO_FIJO.search(producto):
                continue
            if activas >= 1:
                return Eleccion(n, ACTIVAS, activas)
            if no_activas >= 1:
                return Eleccion(n, NO_ACTIVAS, no_activas)
        return None

    eleccion = recorrer(evitar_fijos=True)
    if eleccion is None and any(selectores.PRODUCTO_FIJO.search(p) for p, _, _ in totales):
        eleccion = recorrer(evitar_fijos=False)
    return eleccion


# --------------------- el recuadro de la fila ---------------------
def _campo_celda(celda):
    """Lo que hay que clicar dentro de la celda del total.

    El número suele estar en un ``<input>`` deshabilitado envuelto en un enlace
    ``href="javascript:OpenDetail(...)"``. Un clic en el input deshabilitado no llega al
    enlace, así que se prefiere el enlace; si no hay, el input habilitado; si no, la celda.
    """
    enlaces = celda.find_elements(By.XPATH, ".//a | ./ancestor::a[1]")
    if enlaces:
        return enlaces[0]
    campos = celda.find_elements(By.TAG_NAME, "input")
    if campos and campos[0].is_enabled():
        return campos[0]
    return celda


def _campo(driver, clave, fila):
    """Ubica de nuevo el recuadro de esa fila.

    Se vuelve a buscar en cada intento, en vez de guardar el elemento, porque SIAC repinta
    la tabla y una referencia vieja deja de servir.

    Devuelve:
        El elemento visible para clicar, o None si todavía no está.
    """
    for cabecera, filas in tablas_servicios(driver):
        i = indice_activas(cabecera) if clave == ACTIVAS else indice_no_activas(cabecera)
        if i is None or len(filas) <= fila:
            continue
        try:
            celdas = filas[fila].find_elements(By.TAG_NAME, "td")
            if len(celdas) <= i:
                continue
            campo = _campo_celda(celdas[i])
            if campo.is_displayed():
                return campo
            if celdas[i].is_displayed():
                return celdas[i]              # el enlace no tiene tamaño propio: clic en la celda
        except Exception:
            continue                          # se repintó mientras lo buscaba
    return None


def _esperar_campo(driver, clave, fila, timeout):
    """Reintenta ``_campo`` cada medio segundo hasta ``timeout``. None si no apareció."""
    fin = time.time() + timeout
    while time.time() < fin:
        campo = _campo(driver, clave, fila)
        if campo is not None:
            return campo
        time.sleep(0.5)
    return None


# Para depurar (--debug): HTML del recuadro y de su celda, y los handlers de jQuery que tienen
_JS_DESCRIBIR = r"""
const el = arguments[0], td = el.closest('td'), tr = el.closest('tr');
const ev = x => { try { const d = window.jQuery && jQuery._data(x, 'events');
                        return d ? Object.keys(d).join(',') : ''; } catch (e) { return ''; } };
return {html: el.outerHTML.slice(0, 400), td: td ? td.outerHTML.slice(0, 400) : '',
        eventos: [ev(el), td ? ev(td) : '', tr ? ev(tr) : ''].join(' / ')};
"""

# Secuencia completa de eventos de mouse: hay páginas que solo escuchan mousedown/mouseup
# o dblclick, y no reaccionan a un click suelto
_JS_EVENTOS_MOUSE = r"""
const el = arguments[0];
for (const tipo of ['mouseover', 'mousedown', 'focus', 'mouseup', 'click', 'dblclick']) {
  const e = tipo === 'focus' ? new FocusEvent('focus')
          : new MouseEvent(tipo, {bubbles: true, cancelable: true, view: window, detail: tipo === 'dblclick' ? 2 : 1});
  el.dispatchEvent(e);
}
"""


def _aparecio_detalle(driver, handles_antes, handle_popup):
    """Detecta si ya se abrió el detalle de líneas.

    SIAC lo abre a veces en una ventana nueva y a veces dentro del mismo popup.

    Devuelve:
        El handle de la ventana nueva, el del popup si ahora muestra "Líneas asociadas",
        o None si todavía no aparece.
    """
    nuevas = set(driver.window_handles) - set(handles_antes)
    if nuevas:
        return nuevas.pop()
    try:
        driver.switch_to.window(handle_popup)
        if selectores.DETALLE_LINEAS.search(texto_visible(driver)):
            return handle_popup
    except Exception:
        pass
    return None


def _formas_de_clic(driver):
    """Las formas de clic a probar, de la más directa a la más rebuscada.

    Devuelve:
        ``[(nombre, función(elemento)), ...]``. Cada función lanza excepción si no pudo clicar.
    """
    def ejecutar_enlace(el):
        """Ejecuta el JavaScript del enlace, ej. ``OpenDetail('57268085','01','','A','MOVIL','18')``.

        Es lo que haría el clic, pero sin depender de que el clic llegue al enlace."""
        enlaces = el.find_elements(By.XPATH, "./ancestor-or-self::a[1] | .//a")
        href = (enlaces[0].get_attribute("href") or "") if enlaces else ""
        if not href.lower().startswith("javascript:"):
            raise RuntimeError("el recuadro no tiene enlace javascript:")
        driver.execute_script(unquote(href[len("javascript:"):]))   # Chrome lo da con %20, %27...

    def celda(el):
        """La celda ``<td>`` que contiene al elemento (o el elemento, si ya es una celda)."""
        return el.find_element(By.XPATH, "./ancestor-or-self::td[1]")

    def mouse(el):
        """Mueve el mouse real hasta el elemento y hace clic (con eventos de hover incluidos)."""
        return ActionChains(driver).move_to_element(el).pause(0.3).click().perform()

    return (
        ("enlace OpenDetail", ejecutar_enlace),
        ("clic normal", lambda el: el.click()),
        ("clic con el mouse", mouse),
        ("foco + ENTER", lambda el: (el.click(), el.send_keys(Keys.ENTER))),
        ("eventos de mouse completos", lambda el: driver.execute_script(_JS_EVENTOS_MOUSE, el)),
        ("clic por JavaScript", lambda el: driver.execute_script("arguments[0].click();", el)),
        ("clic en la celda", lambda el: mouse(celda(el))),
        ("doble clic", lambda el: ActionChains(driver).double_click(el).perform()),
    )


def clic_total(driver, eleccion, handles_antes, tiempos):
    """Clica el recuadro elegido hasta que se abra el detalle de líneas.

    Prueba cada forma de ``_formas_de_clic``. Después de cada una espera
    ``tiempos.popup_detalle`` segundos, y solo pasa a la siguiente si el detalle no apareció
    (así no se abren dos detalles).

    Parámetros:
        eleccion: el recuadro a clicar (de ``elegir_fila``).
        handles_antes: ventanas abiertas antes del clic.
        tiempos: la sección ``Tiempos`` de la configuración.

    Devuelve:
        El handle donde quedó el detalle, o None si ninguna forma funcionó.
    """
    handle_popup = driver.current_window_handle
    campo = _esperar_campo(driver, eleccion.clave, eleccion.fila, tiempos.boton_total)
    if campo is None:
        log.warning("No encontré el recuadro de la fila %d para clicarlo.", eleccion.fila + 1)
        return None
    try:
        info = driver.execute_script(_JS_DESCRIBIR, campo)
        log.debug("Recuadro: %s | celda: %s | eventos jQuery: %s", info["html"], info["td"], info["eventos"])
    except Exception:
        pass                                  # solo es información para depurar

    for nombre, hacer_clic in _formas_de_clic(driver):
        driver.switch_to.window(handle_popup)
        campo = _esperar_campo(driver, eleccion.clave, eleccion.fila, tiempos.boton_total)
        if campo is None:
            # el recuadro desapareció: quizá el intento anterior sí abrió el detalle
            log.warning("El recuadro de la fila %d desapareció.", eleccion.fila + 1)
            return _aparecio_detalle(driver, handles_antes, handle_popup)
        centrar(driver, campo)
        time.sleep(0.5)
        try:
            hacer_clic(campo)
        except Exception as e:
            log.info("%s falló (%s); pruebo otra forma.", nombre, type(e).__name__)
            continue
        fin = time.time() + tiempos.popup_detalle
        while time.time() < fin:
            texto = aceptar_alerta_nativa(driver)
            if texto is not None:
                log.warning("Salió una alerta al clicar: %r", texto)
            destino = _aparecio_detalle(driver, handles_antes, handle_popup)
            if destino:
                donde = "misma ventana" if destino == handle_popup else "ventana nueva"
                log.info("Detalle de líneas abierto (%s) con %s.", donde, nombre)
                return destino
            time.sleep(0.5)
        log.info("Con %s no se abrió el detalle; pruebo otra forma.", nombre)
    return None


def abrir_detalle(driver, handle_popup, tiempos):
    """Elige la fila, clica su total y deja el driver en el detalle de líneas.

    Parámetros:
        handle_popup: ventana de Consulta de Productos.
        tiempos: la sección ``Tiempos`` de la configuración.

    Devuelve:
        El handle del detalle de líneas, o None si no hay fila con líneas o ningún clic
        lo abrió (en ese caso el driver vuelve al popup).
    """
    driver.switch_to.window(handle_popup)
    totales = esperar_primera_fila(driver, tiempos.datos)
    if totales is None:
        return None
    eleccion = elegir_fila(totales)
    if eleccion is None:
        log.info("Ninguna fila tiene líneas activas ni no activas; no hay detalle que abrir.")
        return None
    producto = totales[eleccion.fila][0]
    columna = "Total Activas" if eleccion.clave == ACTIVAS else "Total No Activas"
    log.info("Fila %d (%s): clic en %s = %d.", eleccion.fila + 1, producto or "?", columna, eleccion.valor)

    detalle = clic_total(driver, eleccion, driver.window_handles, tiempos)
    if detalle is None:
        log.warning("Ninguna forma de clic en %s abrió el detalle.", columna)
        try:
            driver.switch_to.window(handle_popup)
        except Exception:
            pass
        return None
    driver.switch_to.window(detalle)
    esperar_carga(driver, tiempos.web)
    time.sleep(tiempos.entre_lecturas)
    describir_tablas(driver)                  # solo hace algo con --debug
    return detalle


# ------------------- del detalle a la ficha -------------------
def _contenedor_detalle(driver):
    """Dónde buscar los números del detalle.

    Si el detalle se abrió como ventana modal dentro de la página, devuelve esa modal; si
    no, el driver (la página entera). Así no se clica un número de la tabla de productos
    que queda debajo de la modal.
    """
    for modal in reversed(driver.find_elements(
            By.CSS_SELECTOR, ".modal.in, .modal.show, .modal[style*='display: block'], [role='dialog']")):
        try:
            if modal.is_displayed() and selectores.DETALLE_LINEAS.search(modal.text or ""):
                return modal
        except Exception:
            continue
    return driver


def _primer_numero(driver):
    """El primer número de línea clicable del detalle (enlace, botón, input, span o celda).

    Devuelve:
        ``(elemento, texto)``, o ``(None, "")`` si no hay ninguno.
    """
    xp = (".//tbody//tr//a | .//tbody//tr//button | .//tbody//tr//input"
          " | .//tbody//tr//span | .//tbody//tr//td")
    base = _contenedor_detalle(driver)
    if base is driver:
        xp = xp.replace(".//", "//")          # desde la raíz de la página, no desde un elemento
    for el in base.find_elements(By.XPATH, xp):
        try:
            texto = (el.text or el.get_attribute("value") or "").strip()
            # un número de línea: solo dígitos, espacios, puntos o guiones
            if re.fullmatch(r"\d[\d\s.\-]*", texto) and el.is_displayed():
                return el, texto
        except Exception:
            continue                          # se repintó mientras lo leía
    return None, ""


def clic_primer_numero(driver, handle_siac, tiempos):
    """Clica el primer número del detalle; SIAC pasa a mostrar la ficha de ese cliente.

    Después del clic deja el driver en la ventana de SIAC, que es donde aparece la ficha.

    Devuelve:
        True si clicó un número; False si el detalle no tenía ninguno a tiempo.
    """
    fin = time.time() + tiempos.datos
    el, texto = None, ""
    while el is None and time.time() < fin:
        el, texto = _primer_numero(driver)
        if el is None:
            time.sleep(1)
    if el is None:
        log.warning("Detalle: no encontré ningún número que clicar.")
        return False

    log.info("Detalle: clic en %s.", texto)
    centrar(driver, el)
    time.sleep(0.5)
    clic(driver, el)
    driver.switch_to.window(handle_siac)
    time.sleep(tiempos.tras_numero)
    esperar_carga(driver, tiempos.web)
    return True
