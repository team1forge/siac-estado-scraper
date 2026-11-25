"""Funciones puras: textos, decisiones del flujo y formatos."""
from siac_scraper.navegador.dialogo_windows import escapar_teclas
from siac_scraper.navegador.dom import a_entero, compacta, normaliza
from siac_scraper.resultados import FALLO, SIN_DATOS
from siac_scraper.siac import popups
from siac_scraper.siac.consulta import clasificar
from siac_scraper.siac.detalle import ACTIVAS, NO_ACTIVAS, Eleccion, elegir_fila
from siac_scraper.ui.formato import cortar, formato_miles, formato_tiempo


def test_normaliza_quita_tildes_y_mayusculas():
    assert normaliza("SIAC Único Ñandú") == "siac unico nandu"
    assert normaliza(None) == ""


def test_compacta_y_a_entero():
    assert compacta("  a \n b\t c ") == "a b c"
    assert a_entero("1.234") == 1234
    assert a_entero("—") is None


def test_escapar_teclas():
    assert escapar_teclas("a+b%c{d}") == "a{+}b{%}c{{}d{}}"
    assert escapar_teclas("Clave123") == "Clave123"


def test_formatos():
    assert formato_tiempo(3725) == "01:02:05"
    assert formato_miles(80000) == "80.000"
    assert cortar("uno  dos tres", 7) == "uno do…"


# ------------------------- qué fila clicar -------------------------
def test_elegir_fila_prefiere_activas():
    assert elegir_fila([("MOVIL", 3, 1)]) == Eleccion(0, ACTIVAS, 3)


def test_elegir_fila_usa_no_activas_si_no_hay_activas():
    assert elegir_fila([("MOVIL", 0, 2)]) == Eleccion(0, NO_ACTIVAS, 2)


def test_elegir_fila_salta_filas_sin_lineas():
    assert elegir_fila([("MOVIL", 0, 0), ("MOVIL", 1, 0)]) == Eleccion(1, ACTIVAS, 1)


def test_elegir_fila_evita_hfc_y_ftth():
    totales = [("Plan HFC", 5, 0), ("FTTH 200", 1, 0), ("MOVIL", 0, 4)]
    assert elegir_fila(totales) == Eleccion(2, NO_ACTIVAS, 4)


def test_elegir_fila_usa_fijos_si_no_queda_otra():
    assert elegir_fila([("Plan HFC", 0, 0), ("FTTH", 2, 0)]) == Eleccion(1, ACTIVAS, 2)


def test_elegir_fila_sin_lineas():
    assert elegir_fila([("MOVIL", 0, 0)]) is None
    assert elegir_fila([]) is None


# ------------------------- clasificar el popup -------------------------
def test_clasificar():
    assert clasificar(popups.SIN_RUC, [], "RUC", 3) == (SIN_DATOS, "Consulta de Clientes sin opción RUC")
    assert clasificar(popups.VACIO, [], "RUC", 3) == (SIN_DATOS, "popup sin productos")
    assert clasificar(popups.SIN_RESPUESTA, [], "RUC", 3) == (FALLO, "el popup no cargó en 3 s")
    assert clasificar(popups.DATOS, [], "RUC", 3) == (SIN_DATOS, "popup sin filas de servicios")
    assert clasificar(popups.CLIENTES, [], "RUC", 3) == (SIN_DATOS, "popup sin filas de servicios")
    assert clasificar(popups.DATOS, [("0|1", 0, 0)], "RUC", 3) == (SIN_DATOS, "0 líneas activas y 0 no activas")
    assert clasificar(popups.DATOS, [("0|1", 0, 0), ("0|2", 0, 1)], "RUC", 3) is None
