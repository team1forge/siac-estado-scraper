"""Separa el CSV de resultados en dos: RUCs válidos y RUCs vacíos o bloqueados.

Se usa con ``python -m siac_scraper dividir``. Copia las filas tal cual (con todas sus
columnas); no deduplica: si un RUC aparece dos veces en el CSV, aparece dos veces en la salida.
"""
from __future__ import annotations

import csv
from pathlib import Path

from siac_scraper.resultados import CODIFICACION, VALIDO


def dividir(entrada, salida_validos=None, salida_vacios=None):
    """Escribe ``rucs_validos.csv`` y ``rucs_vacios.csv`` junto al CSV de entrada.

    Todo lo que no es VALIDO (VACIO y BLOQUEADO) va a vacíos.

    Parámetros:
        entrada: el CSV de resultados.
        salida_validos, salida_vacios: rutas de salida; por defecto, junto a la entrada.

    Devuelve:
        ``(cantidad de válidos, cantidad de vacíos)``.
    """
    entrada = Path(entrada)
    salida_validos = Path(salida_validos or entrada.with_name("rucs_validos.csv"))
    salida_vacios = Path(salida_vacios or entrada.with_name("rucs_vacios.csv"))

    with open(entrada, newline="", encoding=CODIFICACION) as f:
        lector = csv.DictReader(f)
        campos = lector.fieldnames
        validos, vacios = [], []
        for fila in lector:
            destino = validos if fila.get("estado_ruc", "").strip().upper() == VALIDO else vacios
            destino.append(fila)

    for ruta, filas in ((salida_validos, validos), (salida_vacios, vacios)):
        with open(ruta, "w", newline="", encoding=CODIFICACION) as f:
            escritor = csv.DictWriter(f, fieldnames=campos)
            escritor.writeheader()
            escritor.writerows(filas)

    print(f"Válidos: {len(validos)} -> {salida_validos}")
    print(f"Vacíos:  {len(vacios)} -> {salida_vacios}")
    return len(validos), len(vacios)
