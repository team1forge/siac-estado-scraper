"""CSV de resultados: formato, estados y lectura para retomar donde se quedó.

Cada RUC consultado agrega una fila. Las columnas son::

    ruc, estado_ruc, cliente, contacto, representante_legal, telefono, email, estado, detalle

``estado`` dice qué pasó (OK, SIN_DATOS, BLOQUEO, FALLO) y ``detalle`` el motivo concreto;
``estado_ruc`` es la versión simple (VALIDO, VACIO, BLOQUEADO) para filtrar en Excel.
Un RUC puede aparecer más de una vez (por ejemplo, si se volvió a consultar): vale su
última fila.
"""
from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Datos del cliente, en el orden de las columnas del CSV
CAMPOS_CLIENTE = ["cliente", "contacto", "representante_legal", "telefono", "email"]

# Columna "estado": qué pasó con el RUC
OK = "OK"                  # se leyó la ficha del cliente
SIN_DATOS = "SIN_DATOS"    # SIAC no tiene datos: "No existen datos", sin opción RUC, 0 líneas...
BLOQUEO = "BLOQUEO"        # alerta "No está autorizado"
FALLO = "FALLO"            # el robot no pudo completar la consulta
ESTADOS = (OK, SIN_DATOS, BLOQUEO, FALLO)

# Columna "estado_ruc": la versión simple del estado
VALIDO, VACIO, BLOQUEADO = "VALIDO", "VACIO", "BLOQUEADO"
ESTADO_RUC = {OK: VALIDO, SIN_DATOS: VACIO, FALLO: VACIO, BLOQUEO: BLOQUEADO}

COLUMNAS = ["ruc", "estado_ruc"] + CAMPOS_CLIENTE + ["estado", "detalle"]

# UTF-8 con BOM para que Excel muestre bien las tildes y la Ñ al abrir el CSV con doble clic
CODIFICACION = "utf-8-sig"


@dataclass
class Resultado:
    """Lo que se encontró de un RUC: una fila del CSV."""

    ruc: str
    estado: str                                       # OK, SIN_DATOS, BLOQUEO o FALLO
    detalle: str = ""                                 # motivo, si no es OK
    datos: dict = field(default_factory=dict)         # {campo de CAMPOS_CLIENTE: valor}

    @property
    def estado_ruc(self):
        """VALIDO, VACIO o BLOQUEADO (un estado desconocido cuenta como VACIO)."""
        return ESTADO_RUC.get(self.estado, VACIO)

    def fila(self):
        """La fila del CSV, en el orden de ``COLUMNAS``."""
        return ([self.ruc, self.estado_ruc] + [self.datos.get(c, "") for c in CAMPOS_CLIENTE]
                + [self.estado, self.detalle])


def interpretar_fila(cabecera, fila):
    """Convierte una fila del CSV en ``Resultado``, leyendo cada valor por nombre de columna.

    También acepta el formato anterior del robot (sin columnas de estado) y deduce el
    estado: OK si tiene cliente, FALLO si el cliente dice "ERROR", SIN_DATOS si está vacía.
    """
    d = dict(zip(cabecera, fila))
    datos = {c: d.get(c, "") for c in CAMPOS_CLIENTE}
    estado, detalle = d.get("estado", ""), d.get("detalle", "")
    if not estado:
        if datos["cliente"] == "ERROR":
            datos = {c: "" for c in CAMPOS_CLIENTE}
            estado, detalle = FALLO, "ERROR (formato anterior)"
        elif datos["cliente"]:
            estado = OK
        else:
            estado, detalle = SIN_DATOS, "vacío, motivo no registrado (formato anterior)"
    return Resultado(d.get("ruc", "").strip(), estado, detalle, datos)


class ArchivoResultados:
    """El CSV de resultados.

    Se escribe una fila por RUC y el archivo se abre y se cierra cada vez: así, si el
    programa se cae, lo guardado no se pierde y la siguiente ejecución retoma desde el
    último RUC.
    """

    def __init__(self, ruta):
        """``ruta``: el CSV (no hace falta que exista todavía)."""
        self.ruta = Path(ruta)

    def _leer(self):
        """``(cabecera, filas)`` del CSV; ``([], [])`` si no existe o está vacío."""
        if not self.ruta.exists():
            return [], []
        with open(self.ruta, newline="", encoding=CODIFICACION) as f:
            filas = list(csv.reader(f))
        return (filas[0], filas[1:]) if filas else ([], [])

    def preparar(self):
        """Deja el CSV con las columnas actuales antes de empezar a escribir.

        Se llama una sola vez al empezar el lote (no en cada fila, porque releer un CSV de
        80k filas en cada guardado haría el robot cada vez más lento).

        - Si tiene el formato anterior del robot, lo convierte sin perder el avance.
        - Si tiene otras columnas, lo renombra a ``<nombre>_anterior_<fecha>.csv`` y el
          lote empieza un CSV nuevo.
        """
        cabecera, filas = self._leer()
        if not cabecera or cabecera == COLUMNAS:
            return
        if "ruc" in cabecera and set(CAMPOS_CLIENTE) <= set(cabecera):
            with open(self.ruta, "w", newline="", encoding=CODIFICACION) as f:
                w = csv.writer(f)
                w.writerow(COLUMNAS)
                for fila in filas:
                    r = interpretar_fila(cabecera, fila)
                    if r.ruc:
                        w.writerow(r.fila())
            log.info("Pasé %s al formato actual (%s).", self.ruta.name, ", ".join(COLUMNAS))
        else:
            respaldo = self.ruta.with_name(f"{self.ruta.stem}_anterior_{time.strftime('%Y%m%d_%H%M%S')}.csv")
            self.ruta.rename(respaldo)
            log.info("%s tenía otras columnas; lo moví a %s.", self.ruta.name, respaldo.name)

    def agregar(self, resultado: Resultado):
        """Agrega una fila al final del CSV (lo crea, con encabezados, si no existe)."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        nuevo = not self.ruta.exists()
        # en modo "a" Python no repite el BOM de utf-8-sig si el archivo ya tiene contenido
        with open(self.ruta, "a", newline="", encoding=CODIFICACION) as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(COLUMNAS)
            w.writerow(resultado.fila())

    def ultimo_ruc(self):
        """El RUC de la última fila (donde se quedó la ejecución anterior), o None.

        Lee el archivo fila por fila sin cargarlo entero en memoria."""
        if not self.ruta.exists():
            return None
        ultimo = None
        with open(self.ruta, newline="", encoding=CODIFICACION) as f:
            filas = csv.reader(f)
            next(filas, None)                 # encabezados
            for fila in filas:
                if fila and fila[0].strip():
                    ultimo = fila[0].strip()
        return ultimo

    def cantidad_rucs(self):
        """Cuántos RUCs distintos tiene el CSV (lo acumulado de todas las ejecuciones)."""
        _, filas = self._leer()
        return len({f[0].strip() for f in filas if f and f[0].strip()})

    def ultimo_por_ruc(self):
        """``{ruc: Resultado}`` con la última fila de cada RUC (en orden de primera aparición)."""
        cabecera, filas = self._leer()
        ultimos = {}
        for fila in filas:
            r = interpretar_fila(cabecera, fila)
            if r.ruc:
                ultimos[r.ruc] = r
        return ultimos

    def cantidad_filas(self):
        """Cuántas filas de datos tiene el CSV (sin los encabezados; cuenta las repetidas)."""
        return len(self._leer()[1])
