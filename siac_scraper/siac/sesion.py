"""Sesión en el navegador: abre el portal, inicia sesión y deja SIAC Único listo para buscar.

Flujo de ``SesionSiac.abrir()``::

    navegador nuevo -> portal (credenciales) -> clic en "SIAC Unico" -> ventana de SIAC
    (credenciales, solo la 1ra vez) -> desplegable en "Documento Identidad"

Entre un RUC y el siguiente, ``reabrir_siac()`` cierra todas las ventanas menos la del
portal y vuelve a abrir SIAC: así cada búsqueda empieza desde una pantalla limpia.
"""
from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By

from siac_scraper.config import Config
from siac_scraper.credenciales import password_portal
from siac_scraper.navegador import dialogo_windows
from siac_scraper.navegador.dom import buscar_en_frames, centrar, clic, xpath_opcion_menu
from siac_scraper.navegador.driver import (aceptar_alerta_nativa, crear_driver, driver_vivo,
                                           esperar_carga, ventanas_vivas)
from siac_scraper.siac import selectores
from siac_scraper.siac.busqueda import seleccionar_tipo_busqueda

log = logging.getLogger(__name__)

ESPERA_RESPUESTA_LOGIN = 15   # segundos esperando que el portal acepte las credenciales


class SesionSiac:
    """Un navegador con el portal y SIAC abiertos.

    Atributos:
        driver: el WebDriver (None antes de ``abrir()`` y después de cerrar).
        handle_portal: ventana del portal; nunca se cierra entre RUCs.
        handle_siac: ventana de SIAC Único; cambia cada vez que se reabre.
        siac_autenticado: SIAC pide credenciales solo la primera vez en cada navegador.
    """

    def __init__(self, cfg: Config, progreso):
        """Prepara la sesión; el navegador recién se abre con ``abrir()``.

        Parámetros:
            cfg: configuración completa.
            progreso: objeto con ``actualizar(**cambios)`` (la pantalla de carga o uno nulo).
        """
        self.cfg = cfg
        self.progreso = progreso
        self.driver = None
        self.handle_portal = None
        self.handle_siac = None
        self.siac_autenticado = False

    # ------------------------- ciclo de vida -------------------------
    def abrir(self):
        """Abre un navegador nuevo, entra al portal y deja SIAC Único listo para buscar.

        Lanza:
            RuntimeError: si no encuentra la opción de SIAC o el desplegable de búsqueda.
            Cualquier error de Selenium si el navegador no arranca.
        """
        nav, portal = self.cfg.navegador, self.cfg.portal
        self.progreso.actualizar(fase="Abriendo el navegador", detalle=nav.nombre.capitalize())
        self.driver = crear_driver(nav)
        self.siac_autenticado = False         # navegador nuevo: SIAC pedirá credenciales otra vez

        self.progreso.actualizar(fase="Iniciando sesión en el portal", detalle=portal.url)
        self.driver.get(portal.url)           # con pageLoadStrategy 'none' vuelve enseguida
        self.autenticar_si_pide("Portal")
        esperar_carga(self.driver, self.cfg.tiempos.web)
        log.info("Portal listo: %s", self.driver.current_url)
        self.handle_portal = self.driver.current_window_handle

        self.progreso.actualizar(fase="Abriendo SIAC Único", detalle=portal.opcion_siac)
        self.abrir_siac()

    def vivo(self):
        """True si el navegador sigue abierto y responde."""
        return driver_vivo(self.driver)

    def cerrar(self):
        """Cierre normal al terminar. Respeta ``Navegador.mantener_abierto``."""
        if self.driver is None or self.cfg.navegador.mantener_abierto:
            return
        try:
            self.driver.quit()
            log.info("Navegador cerrado.")
        except Exception as e:
            log.warning("No pude cerrar el navegador: %s", e)
        self.driver = None

    def descartar(self):
        """Cierra lo que quede de un navegador caído antes de abrir otro.

        A diferencia de ``cerrar()``, ignora ``mantener_abierto`` y espera unos segundos:
        Chrome tarda en soltar la carpeta del perfil, y otro Chrome no puede abrirla mientras.
        """
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass                          # ya estaba muerto
        self.driver = None
        time.sleep(3)

    # -------------------------- credenciales --------------------------
    def _hay_dialogo_auth(self):
        """True si la ventana de autenticación de Windows está esperando.

        Selenium no la ve, pero mientras está abierta la página queda en blanco: se detecta
        porque el ``<body>`` no tiene ningún elemento."""
        try:
            return len(self.driver.find_elements(By.CSS_SELECTOR, "body *")) == 0
        except Exception:
            return True

    def autenticar_si_pide(self, donde):
        """Si sale la ventana de autenticación de Windows, la llena con las credenciales guardadas.

        Parámetros:
            donde: "Portal" o "SIAC", solo para el log.

        Devuelve:
            True si no hizo falta o si se aceptaron; False si no funcionó (el flujo sigue igual,
            y si de verdad no entró, el paso siguiente fallará con un mensaje más claro).
        """
        if not self._hay_dialogo_auth():
            log.info("%s: cargó sin pedir credenciales.", donde)
            return True
        if self._teclear_credenciales(donde):
            return True
        log.warning("%s: el login automático no funcionó; continúo igual.", donde)
        return False

    def _teclear_credenciales(self, donde):
        """Escribe las credenciales y espera hasta 15 s a que la página deje de estar en blanco."""
        c = self.cfg.credenciales
        ventana = dialogo_windows.ventana_navegador(self.cfg.navegador.nombre)
        if ventana is None:
            log.warning("%s: no encontré la ventana del navegador.", donde)
            return False
        usuario, pwd = password_portal(c)
        log.info("%s: tecleando credenciales de %s (%.2f s por tecla)...", donde, usuario, c.pausa_tecla)
        dialogo_windows.teclear(ventana, usuario, pwd, c.pausa_tecla, c.espera_foco)
        del pwd                               # no dejar la contraseña en memoria más de lo necesario
        log.info("%s: credenciales enviadas, esperando respuesta...", donde)
        for _ in range(ESPERA_RESPUESTA_LOGIN):
            if not self._hay_dialogo_auth():
                log.info("%s: credenciales ACEPTADAS.", donde)
                return True
            time.sleep(1)
        return False

    # ------------------------------ SIAC ------------------------------
    def abrir_siac(self):
        """Clic en la opción de SIAC del portal, espera su ventana y elige el tipo de búsqueda.

        Devuelve:
            El handle de la ventana de SIAC (también queda en ``self.handle_siac``).

        Lanza:
            RuntimeError: si la opción no aparece en el portal (el mensaje lista los enlaces
            visibles, para saber si el portal cargó otra cosa).
        """
        d, t, opcion = self.driver, self.cfg.tiempos, self.cfg.portal.opcion_siac
        el = buscar_en_frames(d, xpath_opcion_menu(opcion), timeout=t.web)
        if el is None:
            enlaces = sorted({a.text.strip() for a in d.find_elements(By.TAG_NAME, "a")
                              if a.text.strip() and len(a.text.strip()) < 60})[:60]
            raise RuntimeError(f"No encontré la opción '{opcion}' en el portal. Enlaces visibles: "
                               f"{', '.join(enlaces) or 'ninguno (¿el portal cargó?)'}")

        log.info("Portal: clic en <%s> %r (href=%s)", el.tag_name, el.text.strip() or opcion,
                 el.get_attribute("href"))
        antes = d.window_handles
        centrar(d, el)
        time.sleep(0.3)
        clic(d, el)
        self._ir_a_ventana_siac(antes)

        time.sleep(2)
        if not self.siac_autenticado:
            self.autenticar_si_pide("SIAC")
        else:
            log.info("SIAC: ya autenticado en este navegador; no tecleo credenciales.")

        if not esperar_carga(d, t.web):
            # SIAC a veces abre una ventana intermedia que se cierra sola al redirigir:
            # si la ventana murió mientras cargaba, se busca la definitiva
            log.warning("La ventana se cerró mientras cargaba; busco la de SIAC otra vez.")
            self._ir_a_ventana_siac(antes)
            if not self.siac_autenticado:
                self.autenticar_si_pide("SIAC")
            esperar_carga(d, t.web)
        self.siac_autenticado = True
        log.info("SIAC listo: %s", d.current_url)

        time.sleep(2)                         # que SIAC termine de pintar la barra de búsqueda
        seleccionar_tipo_busqueda(d, self.cfg.portal.tipo_busqueda)
        self.handle_siac = d.current_window_handle
        return self.handle_siac

    def _ir_a_ventana_siac(self, antes):
        """Cambia el driver a la ventana de SIAC (la que tiene "siac" en el título o la URL).

        Si no la reconoce a tiempo, usa la última ventana nueva (puede que aún no tuviera URL)
        o, como último recurso, la última ventana viva.

        Parámetros:
            antes: handles que existían antes del clic, para distinguir las ventanas nuevas.

        Devuelve:
            True si confirmó que es SIAC; False si tuvo que adivinar.

        Lanza:
            RuntimeError: si no queda ninguna ventana abierta.
        """
        d, timeout = self.driver, self.cfg.tiempos.ventana_siac
        fin = time.time() + timeout
        nueva = None
        while time.time() < fin:
            vivas = ventanas_vivas(d)
            for h, titulo, url in vivas:
                if selectores.VENTANA_SIAC.search(url) or selectores.VENTANA_SIAC.search(titulo):
                    d.switch_to.window(h)
                    log.info("Ventana de SIAC: %r -> %s", titulo, url)
                    return True
            nuevas = [v for v in vivas if v[0] not in antes]
            if nuevas:
                nueva = nuevas[-1]            # existe pero aún no resuelve su URL
            time.sleep(1)

        vivas = ventanas_vivas(d)
        if not vivas:
            raise RuntimeError("Se cerraron todas las ventanas del navegador.")
        if nueva and any(v[0] == nueva[0] for v in vivas):
            d.switch_to.window(nueva[0])
            log.warning("Uso la ventana nueva %r; no confirmé que sea SIAC.", nueva[1])
            return False
        log.warning("No apareció la ventana de SIAC en %s s. Ventanas vivas:", timeout)
        for _, titulo, url in vivas:
            log.warning("  %r -> %s", titulo, url)
        d.switch_to.window(vivas[-1][0])
        return False

    def volver_al_portal(self):
        """Cierra TODAS las ventanas (popups, detalle y SIAC) menos la del portal y vuelve a él.

        Lanza:
            RuntimeError: si también se cerró la ventana del portal (hay que reabrir todo).
        """
        d = self.driver
        aceptar_alerta_nativa(d)              # un alert() abierto bloquearía el cambio de ventana
        cerradas = 0
        for h in list(d.window_handles):
            if h == self.handle_portal:
                continue
            try:
                d.switch_to.window(h)
                aceptar_alerta_nativa(d)
                d.close()
                cerradas += 1
            except Exception:
                continue                      # ya se había cerrado
        if self.handle_portal not in d.window_handles:
            raise RuntimeError("Se cerró la ventana del portal.")
        d.switch_to.window(self.handle_portal)
        d.switch_to.default_content()         # buscar_en_frames pudo dejarlo dentro de un iframe
        if selectores.VENTANA_SIAC.search(d.current_url or ""):
            # SIAC se abrió en la misma pestaña del portal: vuelvo a cargar el portal
            d.get(self.cfg.portal.url)
            self.autenticar_si_pide("Portal")
            esperar_carga(d, self.cfg.tiempos.web)
        log.info("Cerré %d ventana(s); de vuelta en el portal.", cerradas)

    def reabrir_siac(self):
        """Deja SIAC limpio para el siguiente RUC: cierra todo y lo abre otra vez desde el portal.

        Devuelve:
            El handle de la nueva ventana de SIAC.
        """
        self.volver_al_portal()
        time.sleep(self.cfg.tiempos.entre_busquedas)
        return self.abrir_siac()
