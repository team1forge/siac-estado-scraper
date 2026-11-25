"""Consulta de un RUC en SIAC, de la búsqueda al resultado que va al CSV.

Es el único punto que conoce el flujo completo de un RUC::

    buscar -> popup -> (Consulta de Clientes: elegir RUC) -> ¿alerta? ¿vacío? ¿datos?
           -> detalle de líneas -> número -> ficha del cliente

Cada paso vive en su propio módulo (``busqueda``, ``popups``, ``tablas``, ``detalle``,
``ficha``); aquí solo se encadenan y se decide el estado final.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from siac_scraper.navegador.driver import esperar_carga
from siac_scraper.resultados import BLOQUEO, FALLO, OK, SIN_DATOS, Resultado
from siac_scraper.siac import popups
from siac_scraper.siac.busqueda import buscar
from siac_scraper.siac.detalle import abrir_detalle, clic_primer_numero
from siac_scraper.siac.ficha import leer_datos_cliente
from siac_scraper.siac.tablas import extraer_totales

log = logging.getLogger(__name__)


def clasificar(contenido, filas, tipo_doc, timeout_datos) -> Optional[Tuple[str, str]]:
    """Decide el resultado cuando ya se sabe por lo que mostró el popup.

    Es una función pura (no toca el navegador) para poder probarla sin SIAC.
    Las alertas no pasan por aquí: necesitan cerrarse antes de guardar.

    Parámetros:
        contenido: lo que devolvió ``popups.esperar_contenido`` (o ``popups.SIN_RUC``).
        filas: ``[(cuenta, activas, no_activas), ...]`` leídas del popup; vacía si no hubo DATOS.
        tipo_doc: tipo de documento buscado en Consulta de Clientes (para el detalle).
        timeout_datos: segundos que se esperó el popup (para el detalle).

    Devuelve:
        ``(estado, detalle)`` si el resultado ya está decidido; None si el RUC tiene líneas
        y hay que abrir el detalle para leer la ficha.
    """
    if contenido == popups.SIN_RUC:
        return SIN_DATOS, f"Consulta de Clientes sin opción {tipo_doc}"
    if contenido == popups.VACIO:
        return SIN_DATOS, "popup sin productos"
    if contenido is popups.SIN_RESPUESTA:
        return FALLO, f"el popup no cargó en {timeout_datos} s"
    if not filas:
        return SIN_DATOS, "popup sin filas de servicios"
    if all(act == 0 and no == 0 for _, act, no in filas):
        return SIN_DATOS, "0 líneas activas y 0 no activas"
    return None


def consultar_ruc(sesion, ruc) -> Resultado:
    """Busca el RUC en SIAC y devuelve lo que se encontró.

    Supone que SIAC ya está abierto con el tipo de búsqueda elegido. Al terminar cierra los
    popups que abrió pero deja la ventana de SIAC; reabrirla para el siguiente RUC le toca
    a quien llama.

    Parámetros:
        sesion: la ``SesionSiac`` abierta.
        ruc: el RUC a consultar.

    Devuelve:
        El ``Resultado`` (estado, detalle y, si hubo ficha, los datos del cliente).

    Lanza:
        Errores de Selenium si el navegador se cae; el robot decide si reintentar.
    """
    d, cfg = sesion.driver, sesion.cfg
    t = cfg.tiempos
    excluir = (sesion.handle_siac, sesion.handle_portal)   # ventanas donde no buscar alertas

    antes = d.window_handles
    buscar(d, ruc)
    popup = popups.esperar_popup(d, antes, t.popup)
    if popup is None:
        return Resultado(ruc, FALLO, f"no apareció el popup en {t.popup} s")

    d.switch_to.window(popup)
    esperar_carga(d, t.web)
    contenido, mensaje, h_alerta = popups.esperar_contenido(d, popup, excluir, t)
    if contenido == popups.CLIENTES:
        # varios clientes con ese documento: elijo el del tipo buscado y sigo con sus productos
        elegido = popups.elegir_cliente(d, popup, cfg.portal.tipo_doc_cliente, t)
        if elegido is None:
            contenido = popups.SIN_RUC
        else:
            popup = elegido
            esperar_carga(d, t.web)
            contenido, mensaje, h_alerta = popups.esperar_contenido(d, popup, excluir, t)

    filas = []
    if contenido == popups.DATOS:
        d.switch_to.window(popup)
        filas = extraer_totales(d, t)

    if contenido in (popups.ALERTA, popups.ALERTA_NATIVA):
        if h_alerta:                          # el alert() nativo ya se aceptó al detectarlo
            popups.aceptar_alerta(d, h_alerta, t)
        # cierro cualquier otra ventana que haya quedado (ej. Consulta de Productos vacía)
        for h in list(d.window_handles):
            if h not in excluir:
                popups.cerrar_popup(d, h, sesion.handle_siac)
        d.switch_to.window(sesion.handle_siac)
        esperar_carga(d, t.web)
        resultado = Resultado(ruc, BLOQUEO, mensaje or "alerta")
    else:
        clasificado = clasificar(contenido, filas, cfg.portal.tipo_doc_cliente, t.datos)
        if clasificado is not None:
            resultado = Resultado(ruc, *clasificado)
        elif not cfg.portal.abrir_ficha:
            resultado = Resultado(ruc, FALLO, "Portal.abrir_ficha desactivado: no se lee la ficha")
        else:
            resultado = _leer_ficha(sesion, ruc, popup)

    popups.cerrar_popup(d, popup, sesion.handle_siac)
    return resultado


def _leer_ficha(sesion, ruc, popup) -> Resultado:
    """Del popup con líneas a la ficha: abre el detalle, clica el número y lee los datos.

    Devuelve OK si la ficha mostró el nombre del cliente; si no, FALLO con el paso que falló
    (y los datos parciales que se hayan leído).
    """
    d, t = sesion.driver, sesion.cfg.tiempos
    h_detalle = abrir_detalle(d, popup, t)
    if h_detalle is None:
        return Resultado(ruc, FALLO, "no se abrió el detalle de líneas")
    if not clic_primer_numero(d, sesion.handle_siac, t):
        return Resultado(ruc, FALLO, "el detalle no tenía número que clicar")
    datos = leer_datos_cliente(d, t.datos)
    popups.cerrar_popup(d, h_detalle, sesion.handle_siac)   # el detalle, si sigue abierto
    if datos.get("cliente"):
        return Resultado(ruc, OK, "", datos)
    return Resultado(ruc, FALLO, "la ficha del cliente no mostró el nombre", datos)
