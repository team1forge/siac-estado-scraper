"""Búsqueda de elementos y lectura de texto en la página.

SIAC repinta el DOM mientras carga, así que una referencia a un elemento puede quedar
obsoleta en cualquier momento (StaleElementReferenceException). Por eso casi todas estas
funciones atrapan la excepción y siguen con el siguiente elemento en vez de fallar.

Las comparaciones de texto ignoran mayúsculas y tildes: el portal escribe "Unico" y "Único"
según la pantalla.
"""
from __future__ import annotations

import re
import time

from selenium.webdriver.common.by import By

# XPath 1.0 no tiene lower-case(): se usa translate() con estas dos tablas, que además
# quitan las tildes. Deben tener la misma longitud (cada letra se cambia por la de su posición).
_MAYUS = "ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÜÑáéíóúüñ"
_MINUS = "abcdefghijklmnopqrstuvwxyzaeiouunaeiouun"
_SIN_TILDES = str.maketrans("áéíóúüñ", "aeiouun")

# Texto visible de la página y de sus iframes (una alerta puede venir dentro de uno).
# Los iframes de otro dominio lanzan error al leerlos: se ignoran.
JS_TEXTO_VISIBLE = r"""
let t = document.body ? document.body.innerText : '';
for (const f of document.querySelectorAll('iframe')) {
  try { t += '\n' + f.contentDocument.body.innerText; } catch (e) {}
}
return t;
"""


# ----------------------------- texto -----------------------------
def normaliza(texto):
    """Minúsculas y sin tildes, para comparar textos de SIAC (None -> "")."""
    return (texto or "").lower().translate(_SIN_TILDES)


def compacta(texto):
    """Colapsa espacios, tabulaciones y saltos de línea en un solo espacio."""
    return " ".join(str(texto or "").split())


def a_entero(texto):
    """Extrae el número de un texto ('1.234' -> 1234). Devuelve None si no hay dígitos."""
    digitos = re.sub(r"[^0-9]", "", texto or "")
    return int(digitos) if digitos else None


# ----------------------------- XPath -----------------------------
def _sin_mayusculas(expr):
    """Envuelve una expresión XPath para compararla en minúsculas y sin tildes."""
    return f"translate({expr},'{_MAYUS}','{_MINUS}')"


def xpath_texto(tags, texto):
    """XPath de los elementos de esos tags cuyo texto contiene ``texto``.

    Parámetros:
        tags: nombres de etiqueta, ej. ``("button", "a")``.
        texto: lo que se busca; no importan mayúsculas ni tildes.
    """
    obj = normaliza(texto)
    tr = _sin_mayusculas("normalize-space(.)")
    return " | ".join(f"//{t}[contains({tr},'{obj}')]" for t in tags)


def xpath_input_valor(texto):
    """XPath de los ``<input>`` cuyo ``value`` contiene ``texto`` (botones ``<input type=button>``)."""
    return f"//input[contains({_sin_mayusculas('@value')},'{normaliza(texto)}')]"


def xpath_boton(texto):
    """XPath de cualquier cosa que parezca un botón con ese texto: button, a, span, div o input."""
    return xpath_texto(("button", "a", "span", "div"), texto) + " | " + xpath_input_valor(texto)


def xpath_opcion_menu(texto):
    """XPath de la opción de un menú: solo el elemento MÁS INTERNO que contiene el texto,
    o uno que lo tenga en ``title``/``alt`` (íconos).

    Se exige el más interno porque el ``<td>`` o ``<li>`` que agrupa varias opciones también
    "contiene" el texto, y al clicar en su centro se caía en otra opción (ej. SIVCO).
    """
    obj = normaliza(texto)
    tr = _sin_mayusculas("normalize-space(.)")
    hoja = f"contains({tr},'{obj}') and not(.//*[contains({tr},'{obj}')])"
    attr = lambda a: _sin_mayusculas(f"normalize-space(@{a})")  # noqa: E731
    partes = [f"//{t}[{hoja}]" for t in ("a", "button", "span", "td", "li")]
    partes.append(f"//*[contains({attr('title')},'{obj}') or contains({attr('alt')},'{obj}')]")
    return " | ".join(partes)


# --------------------------- elementos ---------------------------
def es_visible(el):
    """True si el elemento se ve; False si está oculto o ya no existe en la página."""
    try:
        return el.is_displayed()
    except Exception:
        return False                          # se repintó mientras lo consultaba


def visibles(elementos):
    """Solo los elementos visibles de la lista, en el mismo orden."""
    return [el for el in elementos if es_visible(el)]


def primero_visible(elementos):
    """El primer elemento visible de la lista, o None."""
    return next((el for el in elementos if es_visible(el)), None)


def buscar_en_frames(driver, xpath, timeout):
    """Busca un elemento visible en la página y dentro de cada iframe (SharePoint los usa).

    Reintenta cada segundo hasta ``timeout`` porque los iframes cargan por separado.

    Devuelve:
        El elemento, dejando el driver DENTRO del frame donde está (para poder clicarlo);
        o None, dejando el driver en el documento principal.
    """
    fin = time.time() + timeout
    while time.time() < fin:
        driver.switch_to.default_content()
        for frame in [None] + driver.find_elements(By.TAG_NAME, "iframe"):   # None = la página
            try:
                driver.switch_to.default_content()
                if frame is not None:
                    driver.switch_to.frame(frame)
                el = primero_visible(driver.find_elements(By.XPATH, xpath))
                if el is not None:
                    return el
            except Exception:
                continue                      # el frame se recargó mientras lo recorría
        time.sleep(1)
    driver.switch_to.default_content()
    return None


def centrar(driver, el):
    """Hace scroll hasta dejar el elemento en el centro (un clic fuera de pantalla falla)."""
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)


def clic(driver, el):
    """Clic normal; si otro elemento lo tapa o no es clicable, clic por JavaScript.

    Devuelve:
        "normal" o "JavaScript", según cómo se hizo (para el log).
    """
    try:
        el.click()
        return "normal"
    except Exception:
        driver.execute_script("arguments[0].click();", el)
        return "JavaScript"


def valor_celda(celda):
    """Texto de una celda de tabla. SIAC a veces pone el número dentro de un ``<input>``
    deshabilitado en vez de como texto, así que se mira primero el input."""
    inputs = celda.find_elements(By.TAG_NAME, "input")
    if inputs:
        return (inputs[0].get_attribute("value") or "").strip()
    return celda.text.strip()


def texto_visible(driver):
    """Texto visible de la ventana actual y sus iframes. Devuelve "" si no se pudo leer
    (ventana cerrada o navegando): quien llama debe tratarlo como "no se sabe todavía"."""
    try:
        return driver.execute_script(JS_TEXTO_VISIBLE) or ""
    except Exception:
        return ""
