"""Lectura de las tablas de servicios del popup "Consulta de Productos".

Cada tabla tiene una fila por producto o cuenta (MOVIL, Plan HFC, FTTH...) con las columnas
"Total Activas" y "Total No Activas": cuántas líneas tiene el cliente en ese producto.
Una tabla se reconoce como "de servicios" porque tiene un encabezado "Total Activas".

Las columnas se buscan por el texto del encabezado, no por posición, porque SIAC no siempre
las muestra en el mismo orden.
"""
from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By

from siac_scraper.navegador.dom import a_entero, compacta, normaliza, valor_celda
from siac_scraper.navegador.driver import esperar_carga
from siac_scraper.siac.selectores import SIN_DATOS

log = logging.getLogger(__name__)


# --------------------------- encabezados ---------------------------
def indice_activas(cabecera):
    """Posición de la columna "Total Activas" (sin confundirla con "Total No Activas"), o None."""
    return next((j for j, h in enumerate(cabecera)
                 if "total activas" in normaliza(h) and "no activas" not in normaliza(h)), None)


def indice_no_activas(cabecera):
    """Posición de la columna "Total No Activas", o None."""
    return next((j for j, h in enumerate(cabecera) if "total no activas" in normaliza(h)), None)


def indice_que_contiene(cabecera, texto):
    """Posición de la primera columna cuyo encabezado contiene ``texto`` (sin tildes), o None."""
    return next((j for j, h in enumerate(cabecera) if texto in normaliza(h)), None)


# ----------------------------- tablas -----------------------------
def _filas_con_datos(tabla):
    """Filas del cuerpo de la tabla que tienen celdas ``<td>`` (descarta filas de encabezado)."""
    return [f for f in tabla.find_elements(By.XPATH, ".//tbody/tr") if f.find_elements(By.TAG_NAME, "td")]


def tablas_servicios(driver):
    """Las tablas de servicios de la ventana actual.

    La tabla tiene scroll propio, y a veces el encabezado y el cuerpo son dos ``<table>``
    distintas (encabezado fijo arriba). En ese caso las filas se toman de la tabla siguiente.

    Devuelve:
        ``[(encabezados, filas), ...]``: encabezados como textos; filas como elementos ``<tr>``.
    """
    tablas = []
    for tabla in driver.find_elements(By.TAG_NAME, "table"):
        try:
            cabecera = [compacta(th.text) for th in tabla.find_elements(By.TAG_NAME, "th")]
            if not any("total activas" in normaliza(h) for h in cabecera):
                continue
            filas = _filas_con_datos(tabla)
            if not filas:
                siguiente = tabla.find_elements(By.XPATH, "following::table[1]")
                # solo si es el cuerpo (sin encabezados propios), no la tabla de otra sección
                if siguiente and not any(th.text.strip() for th in siguiente[0].find_elements(By.TAG_NAME, "th")):
                    filas = _filas_con_datos(siguiente[0])
            tablas.append((cabecera, filas))
        except Exception:
            continue                          # la tabla se repintó mientras la leía
    return tablas


def leer_tablas(driver):
    """Lee una vez todas las tablas de servicios.

    Devuelve:
        ``[(clave_cuenta, activas, no_activas), ...]``, una tupla por fila con números.
        ``clave_cuenta`` es ``"<n.º de tabla>|<cuenta>"``. Lista vacía si aún no hay datos.
    """
    filas_datos = []
    for i, (cabecera, filas) in enumerate(tablas_servicios(driver)):
        i_act, i_no = indice_activas(cabecera), indice_no_activas(cabecera)
        if i_act is None or i_no is None:
            continue                          # no es una tabla de servicios
        i_cta = indice_que_contiene(cabecera, "cuenta")
        for fila in filas:
            try:
                celdas = fila.find_elements(By.TAG_NAME, "td")
                if len(celdas) <= max(i_act, i_no):
                    continue                  # fila incompleta, ej. "No existen datos" con colspan
                act = a_entero(valor_celda(celdas[i_act]))
                no = a_entero(valor_celda(celdas[i_no]))
                if act is None and no is None:
                    continue
                cuenta = valor_celda(celdas[i_cta]) if i_cta is not None else str(len(filas_datos))
            except Exception:
                continue                      # fila repintada a mitad de la lectura
            filas_datos.append((f"{i}|{cuenta}", act or 0, no or 0))
    return filas_datos


def popup_sin_datos(driver):
    """True si las tablas ya cargaron y TODAS sus filas dicen "No existen datos" (o similar)."""
    tablas = tablas_servicios(driver)
    if not tablas:
        return False
    try:
        for _, filas in tablas:
            textos = [compacta(f.text) for f in filas]
            if not textos or not all(SIN_DATOS.search(t) for t in textos):
                return False
    except Exception:
        return False                          # se repintó mientras la leía
    return True


def tablas_sin_filas(driver):
    """True si las tablas están en la página pero ninguna fila tiene texto (solo encabezados).

    Puede ser un popup vacío o uno que todavía está cargando: quien llama debe esperar un
    rato antes de darlo por vacío.
    """
    tablas = tablas_servicios(driver)
    if not tablas:
        return False
    try:
        return all(not any(f.text.strip() for f in filas) for _, filas in tablas)
    except Exception:
        return False


def extraer_totales(driver, tiempos):
    """Lee las tablas cuando terminaron de pintarse.

    SIAC agrega las filas de a poco. Para no leer una tabla a medio cargar, se relee cada
    ``tiempos.entre_lecturas`` segundos y se da por buena cuando dos lecturas seguidas
    tienen la misma cantidad de filas.

    Devuelve:
        Las filas de ``leer_tablas``. Si se agota ``tiempos.datos``, la última lectura.
    """
    esperar_carga(driver, tiempos.web)
    fin = time.time() + tiempos.datos
    filas, previas = [], -1
    while time.time() < fin:
        filas = leer_tablas(driver)
        if filas and len(filas) == previas:
            log.info("Popup: %d filas de servicios.", len(filas))
            return filas
        previas = len(filas)
        time.sleep(tiempos.entre_lecturas)
    if filas:
        log.warning("Popup: se agotó el tiempo; me quedo con las %d filas leídas.", len(filas))
    return filas


def esperar_primera_fila(driver, timeout):
    """Espera a que la primera fila de productos tenga Producto y Total Activas.

    Se usa antes de elegir qué fila clicar: sirve para que estén todos los valores, y además
    devuelve el nombre del producto, que hace falta para evitar las filas HFC/FTTH.

    Devuelve:
        ``[(producto, activas, no_activas), ...]`` de todas las filas de esa tabla
        (``no_activas`` es 0 si la tabla no tiene esa columna); None si no cargó a tiempo.
    """
    fin = time.time() + timeout
    while time.time() < fin:
        for cabecera, filas in tablas_servicios(driver):
            i_act = indice_activas(cabecera)
            if i_act is None or not filas:
                continue
            try:
                celdas = filas[0].find_elements(By.TAG_NAME, "td")
                if len(celdas) <= i_act:
                    continue
                valores = [valor_celda(c) for c in celdas]
            except Exception:
                continue                      # se repintó; reintento
            if not (valores[0] and valores[i_act]):
                continue                      # todavía sin datos
            log.debug("Primera fila: %s", " | ".join(
                f"{cabecera[j] if j < len(cabecera) and cabecera[j] else f'col {j}'}={v}"
                for j, v in enumerate(valores)))

            i_no = indice_no_activas(cabecera)
            i_prod = indice_que_contiene(cabecera, "producto") or 0   # sin columna: la primera
            totales = []
            for fila in filas:
                try:
                    tds = fila.find_elements(By.TAG_NAME, "td")
                    prod = compacta(valor_celda(tds[i_prod])) if i_prod < len(tds) else ""
                    act = a_entero(valor_celda(tds[i_act])) if i_act < len(tds) else None
                    no = a_entero(valor_celda(tds[i_no])) if i_no is not None and i_no < len(tds) else None
                except Exception:
                    prod, act, no = "", None, None    # fila repintada a mitad de la lectura
                totales.append((prod, act or 0, no or 0))
            return totales
        time.sleep(1)
    log.warning("No detecté la primera fila de productos en %s s.", timeout)
    return None


def describir_tablas(driver, max_filas=3):
    """Solo con ``--debug``: escribe en el log el título, las columnas y las primeras filas
    de cada tabla de la ventana. Sirve para ajustar el robot cuando SIAC cambia."""
    if not log.isEnabledFor(logging.DEBUG):
        return                                # evita leer el DOM si nadie verá el resultado
    log.debug("Ventana %r | %s", driver.title, driver.current_url)
    for i, tabla in enumerate(driver.find_elements(By.TAG_NAME, "table")):
        try:
            cabecera = [compacta(th.text) for th in tabla.find_elements(By.TAG_NAME, "th")]
            filas = tabla.find_elements(By.XPATH, ".//tbody/tr")
            if not cabecera and not filas:
                continue
            log.debug("  tabla %d (%d filas): %s", i, len(filas), " | ".join(cabecera) or "(sin encabezados)")
            for fila in filas[:max_filas]:
                celdas = [valor_celda(c) for c in fila.find_elements(By.TAG_NAME, "td")]
                if any(celdas):
                    log.debug("    %s", " | ".join(celdas))
        except Exception:
            continue
