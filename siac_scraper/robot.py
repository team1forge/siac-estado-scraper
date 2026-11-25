"""El lote: recorre los RUCs, guarda cada resultado y se recupera si el navegador se cae.

Ciclo de cada RUC::

    consultar_ruc() -> guardar en el CSV -> reabrir SIAC desde el portal -> siguiente RUC

Manejo de errores:

- Error con el navegador vivo (no encontró un botón, se agotó un tiempo...): el RUC se
  guarda como FALLO y se sigue con el siguiente.
- El navegador se cayó: se lanza ``NavegadorCerrado``, ``ejecutar()`` abre uno nuevo y
  retoma desde el último RUC guardado. El RUC que se estaba consultando se reintenta.
- Si el mismo RUC tumba el navegador ``max_caidas_por_ruc`` veces, se guarda como FALLO
  para no quedar atascado. Tras ``max_reinicios_sin_avance`` reinicios seguidos sin guardar
  nada, el robot se rinde.
"""
from __future__ import annotations

import logging
import time

from siac_scraper.config import Config
from siac_scraper.metricas import calcular, reporte
from siac_scraper.navegador.driver import NavegadorCerrado
from siac_scraper.resultados import BLOQUEO, ESTADOS, FALLO, OK, SIN_DATOS, ArchivoResultados, Resultado
from siac_scraper.siac.consulta import consultar_ruc
from siac_scraper.siac.sesion import SesionSiac
from siac_scraper.ui.formato import formato_miles, formato_tiempo

log = logging.getLogger(__name__)

# Cómo se muestra cada estado en los contadores de la pantalla de carga
ETIQUETAS_CONTADOR = {OK: "OK", SIN_DATOS: "Sin datos", BLOQUEO: "Bloqueo", FALLO: "Fallo"}


class ProgresoNulo:
    """Sustituto de la pantalla de carga cuando no se usa (o en pruebas): ignora todo."""

    def actualizar(self, **_):
        """No hace nada; acepta los mismos argumentos que ``PantallaCarga.actualizar``."""


class Robot:
    """Ejecuta el lote completo de RUCs.

    Atributos:
        resultados: el CSV donde se guarda cada RUC.
        contadores: RUCs guardados en ESTA ejecución, por estado (para la pantalla y el resumen).
        sesion: la ``SesionSiac`` actual (None antes de abrirla o tras descartarla).
    """

    def __init__(self, cfg: Config, progreso=None):
        """Prepara el robot; el navegador recién se abre al llamar a ``ejecutar()``.

        Parámetros:
            cfg: configuración completa.
            progreso: objeto con ``actualizar(**cambios)``, normalmente la pantalla de carga.
                Si es None, no se muestra progreso.
        """
        self.cfg = cfg
        self.progreso = progreso or ProgresoNulo()
        self.resultados = ArchivoResultados(cfg.lote.resultados)
        self.contadores = {e: 0 for e in ESTADOS}
        self.sesion = None
        self._caidas_por_ruc = {}                       # ruc -> veces que se cayó el navegador con él

    # ----------------------------- lote -----------------------------
    def ejecutar(self, rucs, reanudar=True):
        """Consulta todos los RUCs y guarda cada resultado en el CSV.

        Si el navegador se cierra a mitad, lo abre de nuevo desde cero (portal -> credenciales
        -> SIAC) y retoma desde el último RUC del CSV.

        Parámetros:
            rucs: lista ordenada de RUCs.
            reanudar: True = empezar después del último RUC del CSV; False = empezar por el
                primero (se usa con ``--ruc``). Tras una caída siempre se reanuda.

        Lanza:
            La excepción original si falla con el navegador abierto fuera de una consulta
            (por ejemplo, no encuentra la opción de SIAC en el portal), o si se agotan los
            reinicios sin avance.
        """
        if not rucs:
            log.warning("No hay RUCs que consultar.")
            return
        self.resultados.preparar()
        maximo = self.cfg.lote.max_reinicios_sin_avance
        sin_avance = 0
        while True:
            avance_antes = self.resultados.ultimo_ruc()
            try:
                self._pasada(rucs, reanudar)
                return
            except Exception as e:
                if not isinstance(e, NavegadorCerrado) and self._navegador_vivo():
                    raise                     # error con el navegador abierto: no lo tapo
                # se cuenta como "sin avance" si desde el último reinicio no se guardó nada
                sin_avance = 0 if self.resultados.ultimo_ruc() != avance_antes else sin_avance + 1
                if sin_avance >= maximo:
                    log.error("%d reinicios seguidos sin avanzar; me rindo.", sin_avance)
                    raise
                motivo = e if isinstance(e, NavegadorCerrado) else f"El navegador se cerró ({type(e).__name__}: {e})"
                log.warning("%s", str(motivo)[:300])
                log.warning("Abro el navegador de nuevo y retomo desde el CSV "
                            "(reinicios seguidos sin avance: %d/%d)...", sin_avance, maximo)
                self.progreso.actualizar(fase="Reiniciando el navegador",
                                         detalle=f"reinicios seguidos sin avance: {sin_avance}/{maximo}")
                self._descartar_sesion()
                reanudar = True               # tras una caída siempre se retoma desde el CSV

    def _inicio(self, rucs, reanudar):
        """Índice del primer RUC pendiente: el siguiente al último del CSV, o 0."""
        if not reanudar:
            return 0
        ultimo = self.resultados.ultimo_ruc()
        if ultimo in rucs:
            inicio = rucs.index(ultimo) + 1
            log.info("El CSV terminó en %s (%d/%d); retomo desde el siguiente.", ultimo, inicio, len(rucs))
            return inicio
        if ultimo:
            log.warning("El último RUC del CSV (%s) no está en la lista; empiezo desde el primero.", ultimo)
        return 0

    def _pasada(self, rucs, reanudar):
        """Un intento con un navegador: abre la sesión y consulta los RUCs pendientes.

        Lanza:
            NavegadorCerrado: si el navegador se cae; ``ejecutar()`` lo reabre y reintenta.
        """
        total = len(rucs)
        inicio = self._inicio(rucs, reanudar)
        if inicio >= total:
            # no se abre el navegador si no queda nada por hacer
            log.info("Todos los RUCs ya están en el CSV; no hay nada que buscar.")
            self.registrar_metricas()
            return

        log.info("Lote de %d RUCs (quedan %d). Resultados -> %s",
                 total, total - inicio, self.resultados.ruta.resolve())
        # se asigna antes de abrir para que, si abrir() falla, ejecutar() pueda ver si el
        # navegador quedó vivo o no
        self.sesion = SesionSiac(self.cfg, self.progreso)
        self.sesion.abrir()
        self.progreso.actualizar(fase="Procesando RUCs", hechos=inicio, total=total)

        for i, ruc in enumerate(rucs[inicio:], inicio + 1):
            log.info("(%d/%d) --- %s ---", i, total, ruc)
            self.progreso.actualizar(detalle=f"RUC {ruc}  ({formato_miles(i)} de {formato_miles(total)})",
                                     hechos=i - 1)
            self._consultar_y_guardar(ruc, i, total)
            self.progreso.actualizar(hechos=i)

            if i < total:
                try:
                    self.sesion.reabrir_siac()
                except Exception as e:
                    # el RUC ya quedó guardado: al reabrir el navegador se sigue con el siguiente
                    raise NavegadorCerrado(f"no pude reabrir SIAC: {e}") from e

        log.info("Lote terminado (%d RUCs). CSV: %s", total, self.resultados.ruta.resolve())
        self.registrar_metricas()

    def _consultar_y_guardar(self, ruc, i, total):
        """Consulta un RUC y guarda el resultado. Un error con el navegador vivo se guarda
        como FALLO; si el navegador se cayó, lanza ``NavegadorCerrado`` sin guardar (salvo
        que ya sea la última caída permitida para este RUC)."""
        try:
            resultado = consultar_ruc(self.sesion, ruc)
            if resultado.estado != OK and not self._navegador_vivo():
                # el "no encontré nada" fue porque se cerró el navegador: no lo guardo como vacío
                raise NavegadorCerrado("el navegador se cerró durante la búsqueda")
        except Exception as e:
            if not self._navegador_vivo():
                self._caida_con_ruc(ruc, e)   # lanza NavegadorCerrado: se reabre y se reintenta
            log.warning("(%d/%d) %s falló: %s. Lo guardo como %s y sigo.", i, total, ruc, e, FALLO)
            resultado = Resultado(ruc, FALLO, f"excepción: {type(e).__name__}: {e}"[:200])
        self._guardar(resultado)
        log.info("(%d/%d) %s -> %s%s", i, total, ruc, resultado.estado,
                 f" ({resultado.detalle})" if resultado.detalle else "")

    def _guardar(self, resultado):
        """Agrega la fila al CSV y actualiza los contadores de la pantalla."""
        self.resultados.agregar(resultado)
        self.contadores[resultado.estado] = self.contadores.get(resultado.estado, 0) + 1
        self.progreso.actualizar(contadores={ETIQUETAS_CONTADOR[e]: self.contadores[e] for e in ESTADOS})

    def _caida_con_ruc(self, ruc, error):
        """Registra que el navegador se cayó con este RUC.

        Tras ``max_caidas_por_ruc`` caídas lo guarda como FALLO, para que la siguiente
        pasada siga con el RUC de después en vez de quedar atascada en este.

        Lanza:
            NavegadorCerrado: siempre.
        """
        veces = self._caidas_por_ruc[ruc] = self._caidas_por_ruc.get(ruc, 0) + 1
        if veces >= self.cfg.lote.max_caidas_por_ruc:
            log.warning("%s: el navegador se cerró %d veces con este RUC; lo guardo como %s.", ruc, veces, FALLO)
            self._guardar(Resultado(ruc, FALLO, f"el navegador se cerró {veces} veces con este RUC"))
        raise NavegadorCerrado(f"se cerró el navegador buscando {ruc} ({type(error).__name__}: {error})"[:300])

    # --------------------------- navegador ---------------------------
    def _navegador_vivo(self):
        """True si hay una sesión y su navegador responde."""
        return self.sesion is not None and self.sesion.vivo()

    def _descartar_sesion(self):
        """Cierra el navegador caído y olvida la sesión, para abrir una nueva."""
        if self.sesion is not None:
            self.sesion.descartar()
        self.sesion = None

    def cerrar(self):
        """Cierra el navegador al terminar. La VPN no se toca: la maneja una persona."""
        if self.sesion is not None:
            self.sesion.cerrar()

    # --------------------------- resúmenes ---------------------------
    def registrar_metricas(self, max_listado=20):
        """Escribe en el log el resumen del CSV (válidos, vacíos, bloqueados y motivos)."""
        for linea in reporte(calcular(self.resultados), self.resultados.ruta.name, max_listado):
            log.info("[métricas] %s", linea)

    def resumen_caida(self, error, inicio):
        """Datos para la ventana que aparece si el programa se cae.

        Parámetros:
            error: la excepción que detuvo el programa.
            inicio: ``time.time()`` del comienzo, para el tiempo de trabajo.

        Devuelve:
            ``(título, destacados, filas, nota)`` en el formato de ``PantallaCarga.mostrar_resumen``.
        """
        extraidos = sum(self.contadores.values())
        tiempo = formato_tiempo(time.time() - inicio)
        try:
            total_csv = formato_miles(self.resultados.cantidad_rucs())
            ultimo = self.resultados.ultimo_ruc() or "-"
        except Exception:
            total_csv, ultimo = "?", "?"      # el CSV pudo ser la causa de la caída
        log.error("Caída: %d RUCs extraídos en esta ejecución, tiempo de trabajo %s.", extraidos, tiempo)
        filas = [
            ("Con datos del cliente (VALIDO)", formato_miles(self.contadores[OK])),
            ("Sin datos (VACIO)", formato_miles(self.contadores[SIN_DATOS])),
            ("Bloqueados", formato_miles(self.contadores[BLOQUEO])),
            ("Fallos del robot", formato_miles(self.contadores[FALLO])),
            ("Total acumulado en el CSV", total_csv),
            ("Último RUC guardado", ultimo),
            ("Inicio del trabajo", time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(inicio))),
        ]
        return ("El programa se detuvo",
                [(formato_miles(extraidos), "RUCs extraídos"), (tiempo, "Tiempo de trabajo")],
                filas,
                f"Motivo: {type(error).__name__}: {error}"[:300])
