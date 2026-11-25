"""Resumen del CSV de resultados: válidos, vacíos (por falta de datos o por fallo) y bloqueados.

Se usa con ``python -m siac_scraper metricas`` y al final de cada lote. Separa el cálculo
(``calcular``) del texto (``reporte``) para poder probar los números sin depender del formato.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from siac_scraper.resultados import (BLOQUEADO, BLOQUEO, CAMPOS_CLIENTE, ESTADO_RUC, ESTADOS, FALLO, OK,
                                     SIN_DATOS, VACIO, VALIDO, ArchivoResultados)


@dataclass
class Metricas:
    """Números del CSV, contando solo la última fila de cada RUC."""

    total: int = 0                            # RUCs distintos
    filas: int = 0                            # filas del CSV (un RUC puede repetirse)
    por_estado: dict = field(default_factory=dict)          # estado -> [Resultado, ...]
    incompletos: dict = field(default_factory=dict)         # campo -> válidos sin ese campo

    def cantidad(self, estado):
        """Cuántos RUCs terminaron en ese estado."""
        return len(self.por_estado.get(estado, []))

    @property
    def vacios(self):
        """RUCs sin datos del cliente, por cualquier motivo (SIN_DATOS, FALLO o estado desconocido)."""
        return sum(len(v) for e, v in self.por_estado.items() if ESTADO_RUC.get(e, VACIO) == VACIO)


def calcular(archivo: ArchivoResultados) -> Metricas:
    """Agrupa los RUCs del CSV por estado y cuenta, de los válidos, cuántos vinieron sin
    cada dato (contacto, teléfono...)."""
    ultimos = archivo.ultimo_por_ruc()
    por_estado = {e: [] for e in ESTADOS}
    for r in ultimos.values():
        # setdefault: también agrupa estados desconocidos (ej. de una versión vieja del robot)
        por_estado.setdefault(r.estado, []).append(r)
    incompletos = {c: sum(1 for r in por_estado[OK] if not r.datos.get(c))
                   for c in CAMPOS_CLIENTE if c != "cliente"}
    return Metricas(len(ultimos), archivo.cantidad_filas(), por_estado, incompletos)


def reporte(m: Metricas, nombre, max_listado=20):
    """El resumen en texto, una línea por elemento de la lista.

    Para cada grupo que no es válido muestra los motivos (columna ``detalle``) ordenados de
    más a menos frecuente, y los primeros ``max_listado`` RUCs.

    Parámetros:
        m: las métricas de ``calcular``.
        nombre: nombre del CSV, para el título.
        max_listado: cuántos RUCs listar por grupo.
    """
    pct = lambda k: f"{100 * k / m.total:5.1f}%" if m.total else "  -  "  # noqa: E731
    lineas = [
        f"===== Resumen de {nombre} =====",
        f"RUCs procesados: {m.total} (filas en el CSV: {m.filas})",
        f"  {VALIDO:<9} ............ {m.cantidad(OK):5d}  {pct(m.cantidad(OK))}",
        f"  {VACIO:<9} ............ {m.vacios:5d}  {pct(m.vacios)}",
        f"    - falta de datos .... {m.cantidad(SIN_DATOS):5d}  {pct(m.cantidad(SIN_DATOS))}",
        f"    - fallo del robot ... {m.cantidad(FALLO):5d}  {pct(m.cantidad(FALLO))}",
    ]
    for e in m.por_estado:
        if e not in ESTADOS and m.cantidad(e):
            lineas.append(f"    - {e} ... {m.cantidad(e):5d}  {pct(m.cantidad(e))}")
    lineas.append(f"  {BLOQUEADO:<9} ............ {m.cantidad(BLOQUEO):5d}  {pct(m.cantidad(BLOQUEO))}")
    if m.cantidad(OK):
        lineas.append("  Válidos sin: " + ", ".join(f"{c} {k}" for c, k in m.incompletos.items()))

    # el motivo concreto dentro de cada grupo, y qué RUCs son
    for estado, titulo in ((SIN_DATOS, "Vacíos por falta de datos"), (FALLO, "Vacíos por fallo del robot"),
                           (BLOQUEO, "Bloqueados")):
        lista = m.por_estado.get(estado, [])
        if not lista:
            continue
        lineas.append(f"{titulo} ({len(lista)}):")
        motivos = Counter(r.detalle or "(sin detalle)" for r in lista)
        for detalle, k in motivos.most_common():
            lineas.append(f"    {k:4d}  {detalle[:100]}")
        rucs = [r.ruc for r in lista]
        resto = f" ... y {len(rucs) - max_listado} más" if len(rucs) > max_listado else ""
        lineas.append(f"  RUCs: {', '.join(rucs[:max_listado])}{resto}")
    if m.total - m.cantidad(OK):
        lineas.append("(filtra la columna 'estado_ruc' o 'estado' del CSV para ver todos los RUCs)")
    return lineas
