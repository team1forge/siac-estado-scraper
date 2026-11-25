"""Configuración del robot.

Todo lo que se suele ajustar está aquí, agrupado por tema en dataclasses. ``Config()`` arma
la configuración completa con los valores por defecto; la línea de comandos
(``python -m siac_scraper --help``) puede sobrescribir los más comunes antes de ejecutar.

Las rutas de ``datos/`` y ``perfiles/`` se calculan desde la raíz del proyecto, no desde la
carpeta en que se lanza el comando, para que el robot encuentre sus archivos siempre.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "datos"          # Excel de entrada y CSV de resultados
DIR_PERFILES = RAIZ / "perfiles"    # perfiles de navegador (cookies y sesión entre ejecuciones)


@dataclass
class Credenciales:
    """Usuario y dónde está guardada su contraseña.

    La contraseña nunca va aquí: se guarda en el Administrador de credenciales de Windows
    con ``python -m siac_scraper guardar-password``.
    """

    # Se puede cambiar sin tocar el código con la variable de entorno SIAC_USUARIO
    usuario: str = field(default_factory=lambda: os.environ.get("SIAC_USUARIO", "D79983538"))
    servicio_keyring: str = "ivanti_vpn"      # no cambiar: ahí ya está guardada la contraseña
    # El portal usa por defecto el mismo usuario y contraseña que la VPN
    reusar_vpn: bool = True
    usuario_portal: str = ""                  # vacío = el mismo usuario; ej. "TIM\\D79983538"
    servicio_keyring_portal: str = "portal_distribuidores"
    # La ventana de autenticación de Windows pierde caracteres si se escribe de golpe,
    # por eso se teclea letra por letra con estas pausas
    pausa_tecla: float = 0.15                 # súbelo si el diálogo se come caracteres
    espera_foco: float = 1.5                  # segundos antes de teclear (que el diálogo tome el foco)

    @property
    def usuario_del_portal(self) -> str:
        """Usuario con el que se entra al portal: ``usuario_portal`` o, si está vacío, ``usuario``."""
        return self.usuario_portal or self.usuario


@dataclass
class Navegador:
    """Qué navegador abre Selenium y con qué opciones."""

    nombre: str = "chrome"                    # "chrome" o "edge"
    # Con perfil propio el navegador conserva cookies y la sesión del portal entre ejecuciones
    usar_perfil: bool = True                  # False = perfil temporal (sin cookies guardadas)
    # Dominios donde el navegador puede usar la sesión de Windows (NTLM/Kerberos) sin preguntar
    auth_allowlist: str = "*tim.com.pe,portaldistribuidores.tim.com.pe"
    mantener_abierto: bool = False            # True = deja el navegador abierto al terminar

    @property
    def perfil(self) -> Optional[Path]:
        """Carpeta del perfil (``perfiles/<navegador>``), o None si se usa uno temporal."""
        return DIR_PERFILES / self.nombre if self.usar_perfil else None


@dataclass
class Portal:
    """Dónde está SIAC y cómo se busca dentro de él."""

    url: str = "http://portaldistribuidores.tim.com.pe:1616/SitePages/inicio.aspx"
    opcion_siac: str = "SIAC Unico"           # texto de la opción del portal que abre SIAC
    tipo_busqueda: str = "Documento Identidad"  # opción del desplegable de búsqueda de SIAC
    tipo_doc_cliente: str = "RUC"             # fila a elegir en "Consulta de Clientes"
    abrir_ficha: bool = True                  # False = no abre el detalle ni lee la ficha


@dataclass
class Tiempos:
    """Esperas, en segundos. Súbelas si la red o SIAC van lentos (muchos FALLO seguidos)."""

    web: float = 6                    # carga del portal y búsqueda de la opción de SIAC
    ventana_siac: float = 5           # que SIAC abra su ventana
    popup: float = 3                  # que aparezca "Consulta de Productos" tras la lupa
    datos: float = 3                  # que el popup pinte sus tablas
    entre_lecturas: float = 1         # pausa entre dos lecturas del popup
    popup_vacio: float = 2            # tablas sin filas durante este tiempo = popup vacío
    boton_total: float = 2            # que el recuadro Total Activas / No Activas esté clicable
    popup_detalle: float = 2          # que aparezca el detalle de líneas tras cada forma de clic
    tras_numero: float = 2            # espera en SIAC tras clicar el número del detalle
    cierre_alerta: float = 3          # que la alerta se cierre tras Aceptar
    entre_busquedas: float = 1.5      # pausa antes de reabrir SIAC para el siguiente RUC


@dataclass
class Lote:
    """Archivos de entrada y salida, y límites para recuperarse de caídas."""

    excel: Path = DIR_DATOS / "80k.xlsx"
    hoja: Union[int, str] = 0                 # índice o nombre de la hoja
    columna: Union[None, int, str] = None     # None = autodetecta (RUC/documento/DNI)
    resultados: Path = DIR_DATOS / "resultado_rucs.csv"
    # Si el navegador se cae, se abre de nuevo y se retoma desde el CSV
    max_reinicios_sin_avance: int = 3         # reinicios seguidos sin guardar nada antes de rendirse
    max_caidas_por_ruc: int = 2               # caídas con el mismo RUC antes de guardarlo como FALLO
    pantalla_carga: bool = True               # ventana de progreso en negro y blanco


@dataclass
class Config:
    """Configuración completa del robot: un grupo por tema."""

    credenciales: Credenciales = field(default_factory=Credenciales)
    navegador: Navegador = field(default_factory=Navegador)
    portal: Portal = field(default_factory=Portal)
    tiempos: Tiempos = field(default_factory=Tiempos)
    lote: Lote = field(default_factory=Lote)
