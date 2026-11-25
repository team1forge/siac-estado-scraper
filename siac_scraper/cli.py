"""Línea de comandos: ``python -m siac_scraper [comando] [opciones]``.

Comandos::

    (sin comando) / ejecutar   consulta los RUCs del Excel (la VPN debe estar conectada)
    guardar-password           guarda la contraseña en el Administrador de credenciales
    verificar-password         prueba la contraseña guardada contra el portal
    metricas                   resumen del CSV de resultados
    dividir                    separa el CSV en válidos y vacíos

Los módulos pesados (Selenium, Tkinter, keyring) se importan dentro de cada comando, para
que ``metricas`` o ``dividir`` funcionen aunque falten las dependencias de Windows.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from siac_scraper.config import Config

# Logger raíz del paquete: todos los módulos escriben en hijos de este (siac_scraper.*)
log = logging.getLogger("siac_scraper")

COMANDOS = ("ejecutar", "guardar-password", "verificar-password", "metricas", "dividir")


def _hoja(valor):
    """Convierte "0", "1"... en índice; cualquier otro texto se toma como nombre."""
    return int(valor) if valor.isdigit() else valor


def _parser():
    """Arma el parser de argumentos con un subcomando por tarea."""
    ap = argparse.ArgumentParser(prog="python -m siac_scraper",
                                 description="Consulta RUCs en SIAC Único y guarda los datos del cliente en un CSV.")
    sub = ap.add_subparsers(dest="comando", metavar="comando")

    p = sub.add_parser("ejecutar", help="consultar los RUCs (comando por defecto)")
    p.add_argument("--excel", type=Path, help="Excel de entrada (por defecto datos/80k.xlsx)")
    p.add_argument("--hoja", type=_hoja, help="índice o nombre de la hoja (por defecto la primera)")
    p.add_argument("--columna", type=_hoja, help="nombre o índice de la columna de RUCs (por defecto se detecta)")
    p.add_argument("--ruc", nargs="+", metavar="RUC", help="consultar solo estos RUCs en vez del Excel")
    p.add_argument("--salida", type=Path, help="CSV de resultados (por defecto datos/resultado_rucs.csv)")
    p.add_argument("--navegador", choices=("chrome", "edge"))
    p.add_argument("--sin-pantalla", action="store_true", help="sin la ventana de progreso")
    p.add_argument("--mantener-abierto", action="store_true", help="no cerrar el navegador al terminar")
    p.add_argument("--debug", action="store_true", help="log detallado (tablas y recuadros que ve el robot)")

    p = sub.add_parser("guardar-password", help="guardar la contraseña en el Administrador de credenciales")
    p.add_argument("--portal", action="store_true", help="la contraseña del portal, si es distinta a la de la VPN")

    sub.add_parser("verificar-password", help="probar la contraseña guardada contra el portal")

    p = sub.add_parser("metricas", help="resumen del CSV: válidos / vacíos / bloqueados")
    p.add_argument("--salida", type=Path, help="CSV de resultados a resumir")

    p = sub.add_parser("dividir", help="separar el CSV en rucs_validos.csv y rucs_vacios.csv")
    p.add_argument("csv", nargs="?", type=Path, help="CSV a dividir (por defecto el de resultados)")
    return ap


def _configurar_log(debug=False):
    """Log a la consola con fecha y nivel; con ``debug`` también los mensajes DEBUG del robot."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    if debug:
        log.setLevel(logging.DEBUG)


def _config_desde_args(args) -> Config:
    """La configuración por defecto, con lo que se haya pasado por línea de comandos encima.

    Usa ``getattr`` porque cada subcomando define opciones distintas.
    """
    cfg = Config()
    lote, nav = cfg.lote, cfg.navegador
    if getattr(args, "excel", None):
        lote.excel = args.excel
    if getattr(args, "hoja", None) is not None:       # 0 es un valor válido
        lote.hoja = args.hoja
    if getattr(args, "columna", None) is not None:
        lote.columna = args.columna
    if getattr(args, "salida", None):
        lote.resultados = args.salida
    if getattr(args, "navegador", None):
        nav.nombre = args.navegador
    if getattr(args, "sin_pantalla", False):
        lote.pantalla_carga = False
    if getattr(args, "mantener_abierto", False):
        nav.mantener_abierto = True
    return cfg


def ejecutar(cfg: Config, rucs=None):
    """Corre el robot completo, con pantalla de carga y resumen si se cae.

    Parámetros:
        cfg: configuración completa.
        rucs: lista de RUCs a consultar; None = leerlos del Excel y retomar desde el CSV.

    Devuelve:
        Código de salida: 0 si terminó bien; 1 si se interrumpió o falló.
    """
    from siac_scraper.entrada import leer_rucs
    from siac_scraper.robot import Robot
    from siac_scraper.ui.pantalla_carga import HandlerPantalla, PantallaCarga

    # se crea siempre, aunque no se muestre: si el programa se cae, mostrar_resumen()
    # usa un MessageBox de Windows en su lugar
    pantalla = PantallaCarga()
    inicio = time.time()
    if cfg.lote.pantalla_carga:
        pantalla.iniciar(inicio)
        log.addHandler(HandlerPantalla(pantalla))     # el último mensaje del log, en la pantalla

    robot = Robot(cfg, pantalla)
    codigo, caida = 0, None
    try:
        if rucs is None:
            rucs = leer_rucs(cfg.lote.excel, cfg.lote.columna, cfg.lote.hoja)
            robot.ejecutar(rucs)
        else:
            robot.ejecutar(rucs, reanudar=False)
        log.info("Proceso terminado; cerrando todo...")
    except KeyboardInterrupt:                 # Ctrl+C o la X de la pantalla de carga
        log.warning("Interrumpido por el usuario; cerrando todo...")
        codigo = 1
    except Exception as e:
        log.exception("Error: %s", e)
        codigo, caida = 1, e
    finally:
        robot.cerrar()

    if caida is not None:
        pantalla.mostrar_resumen(*robot.resumen_caida(caida, inicio))
    elif codigo == 0:
        pantalla.terminar()                   # queda abierta con el resultado hasta cerrarla con la X
    pantalla.cerrar()
    return codigo


def main(argv=None):
    """Punto de entrada.

    Parámetros:
        argv: argumentos (sin el nombre del programa); None = los de la línea de comandos.

    Devuelve:
        Código de salida del proceso.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # sin comando (o empezando por una opción como --excel) = ejecutar
    if not argv or (argv[0] not in COMANDOS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "ejecutar")
    args = _parser().parse_args(argv)
    _configurar_log(getattr(args, "debug", False))
    cfg = _config_desde_args(args)

    if args.comando == "guardar-password":
        from siac_scraper.credenciales import guardar_password
        return 0 if guardar_password(cfg.credenciales, portal=args.portal) else 1

    if args.comando == "verificar-password":
        from siac_scraper.credenciales import verificar_password
        return 0 if verificar_password(cfg.credenciales, cfg.portal.url) else 1

    if args.comando == "metricas":
        from siac_scraper.metricas import calcular, reporte
        from siac_scraper.resultados import ArchivoResultados
        archivo = ArchivoResultados(cfg.lote.resultados)
        if not archivo.ruta.exists():
            print(f"No existe {archivo.ruta.resolve()} todavía.")
            return 1
        # aquí sí se listan todos los RUCs de cada grupo
        print("\n".join(reporte(calcular(archivo), archivo.ruta.name, max_listado=10**6)))
        return 0

    if args.comando == "dividir":
        from siac_scraper.divisor import dividir
        dividir(args.csv or cfg.lote.resultados)
        return 0

    return ejecutar(cfg, args.ruc)
