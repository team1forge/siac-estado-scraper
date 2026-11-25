"""Lectura de los RUCs a consultar desde el Excel de entrada.

El Excel puede venir con o sin encabezados y con la columna de RUCs en cualquier posición:
si no se indica, se usa la primera columna cuyo encabezado diga RUC, documento o DNI.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_COLUMNA_RUC = re.compile(r"ruc|documento|dni", re.I)


def _limpiar(valor):
    """Texto del RUC sin espacios. Excel guarda los números como float, y openpyxl los
    devuelve como ``20123456789.0``: se quita el ``.0``."""
    v = str(valor).strip()
    return v[:-2] if v.endswith(".0") else v


def _resolver_ruta(ruta):
    """La ruta del Excel. Si no existe tal cual, busca el mismo nombre con otra extensión
    (.xlsx, .xls, .xlsm...), por si se escribió sin extensión.

    Lanza:
        FileNotFoundError: si no hay ningún archivo con ese nombre.
    """
    archivo = Path(ruta)
    if archivo.exists():
        return archivo
    candidatos = sorted(archivo.parent.glob(archivo.stem + ".xls*"))
    if not candidatos:
        raise FileNotFoundError(f"No encontré el Excel '{archivo.name}' en {archivo.parent.resolve()}")
    return candidatos[0]


def _indice_columna(cabecera, columna):
    """Posición de la columna de RUCs.

    Parámetros:
        cabecera: textos de la primera fila.
        columna: índice (int), nombre exacto del encabezado (str) o None para detectarla.

    Lanza:
        ValueError: si se pidió un nombre de columna que no existe.
    """
    if isinstance(columna, int):
        return columna
    if columna:
        return cabecera.index(columna)
    idx = next((i for i, h in enumerate(cabecera) if _COLUMNA_RUC.search(h)), None)
    if idx is None:
        log.warning("No identifiqué la columna de RUCs; uso la primera. Encabezados: %s",
                    ", ".join(cabecera) or "(ninguno)")
        return 0
    return idx


def leer_rucs(ruta, columna=None, hoja=0):
    """Lee los RUCs del Excel, en el orden en que aparecen, sin vacíos ni duplicados.

    El orden importa: para retomar una ejecución cortada se busca el último RUC guardado
    en esta lista y se sigue con el que viene después.

    Parámetros:
        ruta: el Excel (si no existe tal cual, se prueba con otras extensiones).
        columna: None = la primera cuyo encabezado diga RUC/documento/DNI; o nombre o índice.
        hoja: índice o nombre de la hoja.

    Devuelve:
        Lista de RUCs como texto.

    Lanza:
        FileNotFoundError: si no existe el Excel.
    """
    from openpyxl import load_workbook

    archivo = _resolver_ruta(ruta)
    # read_only: no carga todo el archivo en memoria (el Excel puede tener 80k filas)
    wb = load_workbook(archivo, read_only=True, data_only=True)
    try:
        ws = wb[hoja] if isinstance(hoja, str) else wb.worksheets[hoja]
        filas = ws.iter_rows(values_only=True)
        cabecera = ["" if c is None else str(c).strip() for c in next(filas, ())]
        idx = _indice_columna(cabecera, columna)

        valores, vistos = [], set()
        primera = cabecera[idx] if idx < len(cabecera) else ""
        if primera.replace(" ", "").isdigit() and len(primera) >= 8:
            # el archivo no tenía encabezados: la primera fila ya es un RUC
            primera = _limpiar(primera)
            valores.append(primera)
            vistos.add(primera)
        for fila in filas:
            if idx >= len(fila) or fila[idx] is None:
                continue
            v = _limpiar(fila[idx])
            if v and v not in vistos:
                vistos.add(v)
                valores.append(v)
    finally:
        wb.close()

    log.info("%s: %d RUCs en la columna %r", archivo.name, len(valores),
             cabecera[idx] if idx < len(cabecera) else idx)
    return valores
