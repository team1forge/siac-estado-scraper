"""Ventanas que abre SIAC después de buscar un RUC.

Tras presionar la lupa, SIAC puede mostrar:

- "Consulta de Productos": tablas con las líneas del cliente (lo normal).
- "Consulta de Clientes": el documento tiene varios clientes (RUC, pasaporte...) y hay que
  elegir el de tipo RUC; después aparece Consulta de Productos.
- Una alerta "Usted no está autorizado...": como ventana propia o como ``alert()`` de
  JavaScript. El RUC se guarda como BLOQUEO.

``esperar_contenido()`` distingue estos casos y devuelve una de las constantes de abajo.
"""
from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By

from siac_scraper.navegador.dom import (JS_TEXTO_VISIBLE, buscar_en_frames, centrar, clic, compacta,
                                        normaliza, texto_visible, visibles, xpath_boton,
                                        xpath_input_valor, xpath_texto)
from siac_scraper.navegador.driver import aceptar_alerta_nativa, nuevas_ventanas, ventanas_vivas
from siac_scraper.siac import selectores
from siac_scraper.siac.tablas import leer_tablas, popup_sin_datos, tablas_sin_filas

log = logging.getLogger(__name__)

# Lo que puede mostrar el popup tras la búsqueda (valor de retorno de esperar_contenido)
DATOS = "datos"                  # tablas de servicios con números
VACIO = "vacio"                  # "No existen datos" o tablas sin filas
CLIENTES = "clientes"            # lista "Consulta de Clientes" (varios clientes con ese documento)
SIN_RUC = "sin_ruc"              # Consulta de Clientes sin fila del tipo de documento buscado
ALERTA = "alerta"                # ventana de alerta de SIAC ("No está autorizado...")
ALERTA_NATIVA = "alerta_nativa"  # alert() de JavaScript
SIN_RESPUESTA = None             # no mostró nada reconocible a tiempo

ESPERA_ACEPTAR_ALERTA = 10       # segundos buscando el botón Aceptar de la alerta


# ------------------------------ popup ------------------------------
def esperar_popup(driver, handles_antes, timeout):
    """Espera la ventana que abre SIAC tras la búsqueda.

    Parámetros:
        handles_antes: ventanas abiertas antes de buscar (para reconocer la nueva).
        timeout: segundos de espera.

    Devuelve:
        El handle de la ventana nueva (Consulta de Productos o una alerta), con el driver
        ya en ella. Si apareció una ventana sin el título esperado, la usa igual.
        None si no se abrió ninguna.
    """
    fin = time.time() + timeout
    nuevo = None
    while time.time() < fin:
        for h in nuevas_ventanas(driver, handles_antes):
            try:
                driver.switch_to.window(h)
                nuevo = h
                if texto_alerta(driver):      # la ventana nueva es una alerta: no espero más
                    log.info("Ventana nueva con alerta: %s", driver.current_url)
                    return h
                if (selectores.POPUP_PRODUCTOS.search(driver.current_url)
                        or selectores.POPUP_PRODUCTOS.search(driver.title or "")):
                    log.info("Popup: %s", driver.current_url)
                    return h
            except Exception:
                continue                      # todavía abriendo o ya se cerró
        time.sleep(1)
    if nuevo and nuevo in driver.window_handles:
        log.info("Ventana nueva sin el título esperado; la uso igual.")
        return nuevo
    return None


def esperar_contenido(driver, popup, excluir, tiempos):
    """Espera a que el popup muestre algo reconocible, o a que salga una alerta.

    Cada segundo revisa, en este orden: un ``alert()`` nativo, una ventana de alerta (en
    cualquier ventana menos las de ``excluir``), y el contenido del popup.

    Parámetros:
        popup: handle del popup de la búsqueda.
        excluir: handles donde no se buscan alertas (SIAC y el portal).
        tiempos: la sección ``Tiempos`` de la configuración.

    Devuelve:
        ``(contenido, mensaje, handle)``:
        - contenido: DATOS, VACIO, CLIENTES, ALERTA, ALERTA_NATIVA o SIN_RESPUESTA.
        - mensaje: el texto de la alerta ("" en los demás casos).
        - handle: dónde quedó (la ventana de la alerta; None si fue un alert() nativo).
    """
    fin = time.time() + tiempos.datos
    vacio_desde = None                        # desde cuándo las tablas se ven sin filas
    while time.time() < fin:
        texto = aceptar_alerta_nativa(driver)
        if texto is not None:
            return ALERTA_NATIVA, texto, None

        h, mensaje = buscar_ventana_alerta(driver, excluir)
        if h:
            return ALERTA, mensaje, h

        if popup in driver.window_handles:
            try:
                driver.switch_to.window(popup)
                if leer_tablas(driver):
                    return DATOS, "", popup
                if popup_sin_datos(driver):
                    return VACIO, "", popup
                if selectores.CONSULTA_CLIENTES.search(texto_visible(driver)):
                    return CLIENTES, "", popup
                if tablas_sin_filas(driver):
                    # puede estar cargando: solo lo doy por vacío si sigue así un rato
                    vacio_desde = vacio_desde or time.time()
                    if time.time() - vacio_desde >= tiempos.popup_vacio:
                        return VACIO, "", popup
                else:
                    vacio_desde = None
            except Exception:
                pass                          # el popup está navegando; reviso en la próxima vuelta
        time.sleep(1)
    return SIN_RESPUESTA, "", popup


def cerrar_popup(driver, handle_popup, handle_siac):
    """Cierra un popup y deja el driver en la ventana de SIAC.

    Primero intenta con el botón "Cerrar" del propio popup (algunas pantallas de SIAC
    limpian su estado al cerrarse así); si no hay botón o no se cerró, cierra la ventana.
    Si la ventana de SIAC ya no existe, deja el driver en la última ventana viva.
    """
    if handle_popup in driver.window_handles:
        try:
            # el botón se busca SOLO en el popup (en SIAC "Cerrar" podría ser "Cerrar sesión")
            driver.switch_to.window(handle_popup)
            xp = xpath_texto(("button", "a", "span"), "cerrar") + " | " + xpath_input_valor("cerrar")
            botones = visibles(driver.find_elements(By.XPATH, xp))
            if botones:
                clic(driver, botones[0])
                time.sleep(1.5)
        except Exception as e:
            log.debug("Botón Cerrar no utilizable: %s", e)

        if handle_popup in driver.window_handles:
            try:
                driver.switch_to.window(handle_popup)
                driver.close()
            except Exception:
                pass

    try:
        driver.switch_to.window(handle_siac)
    except Exception:
        vivas = ventanas_vivas(driver)
        if vivas:
            driver.switch_to.window(vivas[-1][0])


# ----------------------------- alertas -----------------------------
def texto_alerta(driver):
    """El mensaje si la ventana ACTUAL muestra una alerta de SIAC, o "" si no.

    Devuelve la línea del mensaje ("Usted no está autorizado..."), no el título "Alerta".
    """
    texto = texto_visible(driver)
    if not selectores.ALERTA.search(texto):
        return ""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    return next((l for l in lineas if selectores.ALERTA.search(l) and normaliza(l) != "alerta"), "Alerta")


def buscar_ventana_alerta(driver, excluir=()):
    """Recorre las ventanas abiertas (menos las de ``excluir``) buscando una alerta.

    Devuelve:
        ``(handle, mensaje)`` dejando el driver en esa ventana; o ``(None, "")``.
    """
    for h in driver.window_handles:
        if h in excluir:
            continue
        try:
            driver.switch_to.window(h)
        except Exception:
            continue                          # se cerró mientras recorría
        mensaje = texto_alerta(driver)
        if mensaje:
            return h, mensaje
    return None, ""


def aceptar_alerta(driver, handle_alerta, tiempos):
    """Presiona Aceptar en la ventana de la alerta (también si el botón está en un iframe).

    Si no hay botón o la ventana no se cierra sola, la cierra desde el navegador.
    Nunca lanza excepción: si al final sigue abierta, lo deja anotado en el log y sigue.
    """
    driver.switch_to.window(handle_alerta)
    boton = buscar_en_frames(driver, xpath_boton("aceptar"), timeout=ESPERA_ACEPTAR_ALERTA)
    if boton is None:
        log.warning("Alerta: no encontré el botón Aceptar.")
    else:
        # el xpath puede devolver el <span> de adentro: subo al botón o enlace si lo hay
        padre = boton.find_elements(By.XPATH, "./ancestor-or-self::*[self::button or self::a][1]")
        clic(driver, padre[0] if padre else boton)
        if _esperar_cierre_alerta(driver, handle_alerta, tiempos.cierre_alerta):
            log.info("Alerta aceptada.")
            return

    try:
        driver.switch_to.window(handle_alerta)
        driver.close()
        log.info("Alerta: no se cerró sola; la cerré desde el navegador.")
    except Exception:
        pass
    if not _esperar_cierre_alerta(driver, handle_alerta, 5):
        log.warning("Alerta: la ventana sigue abierta; continúo igual.")


def _esperar_cierre_alerta(driver, handle_alerta, timeout):
    """True cuando la ventana de la alerta desaparece (o pasa a mostrar otra cosa)."""
    fin = time.time() + timeout
    while time.time() < fin:
        if handle_alerta not in driver.window_handles:
            return True
        try:
            driver.switch_to.window(handle_alerta)
            if not texto_alerta(driver):      # la misma ventana pasó a otra página
                return True
        except Exception:
            return True                       # se cerró mientras la consultaba
        time.sleep(0.5)
    return False


# ------------------------ Consulta de Clientes ------------------------
def _fila_con_tipo(driver, tipo):
    """La fila ``<tr>`` visible que tiene una celda exactamente igual a ``tipo`` (ej. "RUC").

    Se exige la celda exacta (no "contiene") para no confundir "RUC" con, por ejemplo,
    una razón social que tenga esas letras."""
    objetivo = normaliza(tipo)
    for fila in driver.find_elements(By.XPATH, "//tbody/tr"):
        try:
            celdas = [normaliza(compacta(td.text)) for td in fila.find_elements(By.TAG_NAME, "td")]
            if objetivo in celdas and fila.is_displayed():
                return fila
        except Exception:
            continue                          # se repintó mientras la leía
    return None


def elegir_cliente(driver, popup, tipo, tiempos):
    """En "Consulta de Clientes": marca la fila del tipo de documento buscado y presiona Seleccionar.

    Parámetros:
        popup: handle de la ventana de Consulta de Clientes.
        tipo: Tipo Documento a elegir, ej. "RUC".
        tiempos: la sección ``Tiempos`` de la configuración.

    Devuelve:
        El handle donde queda "Consulta de Productos" (la misma ventana u otra nueva), o
        None si no hay fila de ese tipo o no se pudo seleccionar.
    """
    driver.switch_to.window(popup)
    fin = time.time() + tiempos.datos
    fila = None
    while fila is None and time.time() < fin:
        fila = _fila_con_tipo(driver, tipo)
        if fila is None:
            time.sleep(1)
    if fila is None:
        log.info("Consulta de Clientes: ninguna fila con Tipo Documento %r.", tipo)
        return None

    log.info("Consulta de Clientes: elijo la fila %s", " | ".join(fila.text.split("\n")))
    radios = fila.find_elements(By.XPATH, ".//input[@type='radio' or @type='checkbox']")
    marca = radios[0] if radios else fila.find_elements(By.TAG_NAME, "td")[0]
    centrar(driver, marca)
    clic(driver, marca)                       # por JavaScript si el radio está oculto por estilo
    time.sleep(0.5)
    if radios and not radios[0].is_selected():
        # último recurso: marcarlo directamente y avisar a la página con los eventos que escucha
        driver.execute_script(
            "arguments[0].checked = true;"
            " arguments[0].dispatchEvent(new Event('change', {bubbles: true}));"
            " arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true}));", radios[0])

    xp = xpath_texto(("button", "a"), "seleccionar") + " | " + xpath_input_valor("seleccionar")
    botones = visibles(driver.find_elements(By.XPATH, xp))
    if not botones:
        log.warning("Consulta de Clientes: no encontré el botón Seleccionar.")
        return None
    antes = driver.window_handles
    clic(driver, botones[0])

    # Consulta de Productos puede cargar en esta misma ventana o abrir otra
    fin = time.time() + tiempos.popup
    while time.time() < fin:
        aceptar_alerta_nativa(driver)
        nuevas = nuevas_ventanas(driver, antes)
        if nuevas:
            driver.switch_to.window(nuevas[-1])
            return nuevas[-1]
        if popup in driver.window_handles:
            try:
                driver.switch_to.window(popup)
                # sin texto_visible(): si falla la lectura NO hay que darlo por cargado
                texto = driver.execute_script(JS_TEXTO_VISIBLE) or ""
                if not selectores.CONSULTA_CLIENTES.search(texto):
                    return popup
            except Exception:
                pass                          # está navegando
        time.sleep(1)
    log.warning("Consulta de Clientes: tras Seleccionar no apareció Consulta de Productos.")
    return None
