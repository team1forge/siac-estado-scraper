"""Formatos de números y tiempos para mostrar en pantalla y en el log.

Están aparte de ``pantalla_carga`` para que el robot pueda usarlos sin importar Tkinter.
"""


def formato_tiempo(segundos):
    """Duración como ``HH:MM:SS`` (ej. 3725 -> ``01:02:05``). Los negativos se muestran como 0."""
    s = max(0, int(segundos))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def formato_miles(n):
    """Número con punto como separador de miles, al estilo peruano (80000 -> ``80.000``)."""
    return f"{n:,}".replace(",", ".")


def cortar(texto, n):
    """Colapsa los espacios y recorta a ``n`` caracteres, terminando en "…" si sobraba texto."""
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= n else texto[:n - 1] + "…"
