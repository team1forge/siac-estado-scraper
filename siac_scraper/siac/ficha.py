"""Lectura del panel "Datos del Cliente" de SIAC.

La ficha no tiene ids estables: los datos están como pares "etiqueta: valor" en celdas,
labels o divs. Se busca cada etiqueta por su texto exacto y se toma el elemento de al lado.
Las etiquetas posibles de cada campo están en ``selectores.ETIQUETAS_CLIENTE``.
"""
from __future__ import annotations

import logging
import re
import time

from siac_scraper.resultados import CAMPOS_CLIENTE
from siac_scraper.siac.selectores import ETIQUETAS_CLIENTE

log = logging.getLogger(__name__)

# arguments[0] = {campo: [etiquetas...]}. Para cada campo prueba sus etiquetas en orden;
# compara el texto exacto del elemento (sin tildes ni mayúsculas) y devuelve el texto del
# elemento siguiente, o del siguiente de su padre (cuando la etiqueta está en un <b> dentro
# de la celda). Ignora los elementos ocultos (offsetParent null).
_JS_DATOS_CLIENTE = r"""
const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase()
                           .normalize('NFD').replace(/[̀-ͯ]/g, '');
const els = document.querySelectorAll('td,th,label,dt,dd,div,span,strong,b,p');
function valor(etiquetas) {
  for (const et of etiquetas) {
    for (const el of els) {
      if (!el.offsetParent || norm(el.innerText) !== et) continue;
      const sib = el.nextElementSibling || (el.parentElement && el.parentElement.nextElementSibling);
      const v = sib ? sib.innerText.replace(/\s+/g, ' ').trim() : '';
      if (v) return v;
    }
  }
  return '';
}
const out = {};
for (const [campo, etiquetas] of Object.entries(arguments[0])) out[campo] = valor(etiquetas);
return out;
"""


def leer_datos_cliente(driver, timeout):
    """Lee los datos del cliente de la ficha que muestra la ventana actual de SIAC.

    Relee cada segundo hasta que aparezca el nombre del cliente (la ficha se pinta de a
    poco) o hasta ``timeout``.

    Devuelve:
        ``{campo: valor}`` con todos los ``CAMPOS_CLIENTE`` ("" en los que no aparecieron).
        Si "cliente" queda vacío, la ficha no cargó.
    """
    fin = time.time() + timeout
    datos = {}
    while time.time() < fin:
        try:
            datos = driver.execute_script(_JS_DATOS_CLIENTE, ETIQUETAS_CLIENTE) or {}
        except Exception:
            pass                              # la página aún se está pintando
        if datos.get("cliente"):
            break
        time.sleep(1)
    datos = {c: datos.get(c, "") for c in CAMPOS_CLIENTE}
    # junto al nombre hay un botón "..." (ver más) cuyo texto se cuela en la lectura
    datos["cliente"] = re.sub(r"\s*\.\.\.\s*$", "", datos["cliente"])
    log.info("Ficha: %s", " | ".join(f"{c}: {datos[c]!r}" for c in CAMPOS_CLIENTE))
    return datos
