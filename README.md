# siac-scraper

Robot que consulta RUCs en **SIAC Único** (portal de distribuidores de TIM) y guarda en un CSV los datos del cliente: razón social, contacto, representante legal, teléfono y correo.

Funciona solo en **Windows**: usa `pywinauto` para teclear las credenciales en la ventana de autenticación de Windows, el Administrador de credenciales para la contraseña y Tkinter para la pantalla de carga. Las pruebas sí corren en cualquier sistema.

## Requisitos

- Windows 10 u 11.
- Python 3.9 o superior, instalado desde python.org con la opción **tcl/tk and IDLE** marcada (trae Tkinter).
- Google Chrome o Microsoft Edge.
- Acceso a la VPN de TIM y un usuario del portal de distribuidores.

## Instalación

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Selenium descarga solo el driver del navegador (Selenium Manager). Si hay un `chromedriver.exe` viejo en el PATH (por ejemplo, en `C:\chromedriver`), bórralo o actualízalo: si no coincide con la versión de Chrome, el navegador no abre.

## Uso

1. **Conecta la VPN a mano.** El robot no la toca.
2. La primera vez, guarda la contraseña en el Administrador de credenciales de Windows:
   ```
   python -m siac_scraper guardar-password
   ```
3. Pon el Excel con los RUCs en `datos/80k.xlsx` (la columna RUC/documento se detecta sola) y ejecuta:
   ```
   python -m siac_scraper
   ```

Si la ejecución se corta, vuelve a lanzar el mismo comando: retoma desde el último RUC guardado en el CSV.

### Comandos

| Comando | Qué hace |
|---|---|
| `python -m siac_scraper` | Consulta todos los RUCs del Excel (igual que `ejecutar`). |
| `python -m siac_scraper --ruc 20123456789` | Consulta solo esos RUCs (puedes pasar varios). |
| `python -m siac_scraper --excel otro.xlsx --salida otro.csv` | Otro Excel de entrada y otro CSV de salida. |
| `python -m siac_scraper --navegador edge` | Usa Edge en vez de Chrome. |
| `python -m siac_scraper --sin-pantalla` | Sin la ventana de progreso. |
| `python -m siac_scraper --debug` | Log detallado: tablas, recuadros y eventos que ve el robot. |
| `python -m siac_scraper guardar-password` | Guarda la contraseña de la VPN (también la usa el portal). |
| `python -m siac_scraper guardar-password --portal` | Guarda una contraseña aparte para el portal (ver Configuración). |
| `python -m siac_scraper verificar-password` | Prueba la contraseña guardada contra el portal. |
| `python -m siac_scraper metricas` | Resumen del CSV: válidos, vacíos (por falta de datos o fallo) y bloqueados. |
| `python -m siac_scraper dividir` | Separa el CSV en `rucs_validos.csv` y `rucs_vacios.csv`. |

`python -m siac_scraper ejecutar --help` muestra todas las opciones.

## Resultado

`datos/resultado_rucs.csv` (UTF-8 con BOM, para que Excel muestre bien las tildes), con las columnas:

```
ruc, estado_ruc, cliente, contacto, representante_legal, telefono, email, estado, detalle
```

| `estado` | `estado_ruc` | Significado |
|---|---|---|
| `OK` | `VALIDO` | Se leyó la ficha del cliente. |
| `SIN_DATOS` | `VACIO` | SIAC no tiene datos para ese RUC. |
| `FALLO` | `VACIO` | El robot no pudo completar la consulta (en `detalle` está el motivo). |
| `BLOQUEO` | `BLOQUEADO` | SIAC respondió "No está autorizado". |

Si el navegador se cae, el robot lo abre de nuevo y retoma desde el último RUC guardado. Si el mismo RUC tumba el navegador `max_caidas_por_ruc` veces, lo guarda como `FALLO` y sigue; tras `max_reinicios_sin_avance` reinicios seguidos sin guardar nada, se detiene.

## Configuración

Está en [siac_scraper/config.py](siac_scraper/config.py), agrupada por tema:

| Grupo | Lo que más se cambia |
|---|---|
| `Credenciales` | `usuario` (o la variable de entorno `SIAC_USUARIO`). `reusar_vpn = False` y `usuario_portal` si el portal usa otras credenciales. `pausa_tecla` y `espera_foco` si la ventana de Windows se come caracteres. |
| `Navegador` | `nombre` (`"chrome"` o `"edge"`), `mantener_abierto`, `usar_perfil`. |
| `Portal` | URL del portal, nombre de la opción de SIAC, tipo de búsqueda. |
| `Tiempos` | Todas las esperas, en segundos. Súbelas si la red está lenta o hay muchos `FALLO`. |
| `Lote` | Excel, hoja, columna, CSV de salida, límites de reinicio y la pantalla de carga. |

Los textos con los que el robot reconoce las pantallas de SIAC (títulos de popups, mensajes de alerta, etiquetas de la ficha) están en [siac_scraper/siac/selectores.py](siac_scraper/siac/selectores.py). Si SIAC cambia un texto, normalmente basta con tocar ese archivo.

## Cómo está organizado

```
siac_scraper/
├── cli.py              línea de comandos
├── config.py           configuración
├── robot.py            el lote: recorre los RUCs, guarda y se recupera de caídas
├── entrada.py          lee los RUCs del Excel
├── resultados.py       CSV de resultados: estados, formato, retomar
├── metricas.py         resumen del CSV
├── divisor.py          separa válidos y vacíos
├── credenciales.py     contraseñas en el Administrador de credenciales
├── navegador/          Selenium genérico (no sabe nada de SIAC)
│   ├── driver.py         crear el navegador, ventanas, alert()
│   ├── dom.py            XPath sin tildes, clics, lectura de celdas
│   └── dialogo_windows.py  teclea en la ventana de autenticación de Windows
├── siac/               el flujo dentro del portal y de SIAC
│   ├── sesion.py         portal -> credenciales -> SIAC Único
│   ├── busqueda.py       tipo de búsqueda, caja y lupa
│   ├── popups.py         Consulta de Productos / de Clientes, alertas
│   ├── tablas.py         tablas de servicios (Total Activas / No Activas)
│   ├── detalle.py        fila a clicar -> detalle de líneas -> número
│   ├── ficha.py          datos del cliente
│   ├── consulta.py       un RUC de principio a fin
│   └── selectores.py     textos y patrones de SIAC
└── ui/
    ├── pantalla_carga.py ventana de progreso y resumen si se cae
    └── formato.py
```

El flujo de cada RUC: `robot.py` llama a `consulta.consultar_ruc()`, que busca el RUC, espera el popup, decide qué mostró (datos, vacío, varios clientes o alerta), abre el detalle de líneas y lee la ficha. Después `robot.py` guarda la fila y le pide a `sesion.py` que cierre todo y reabra SIAC para el siguiente.

## Pruebas

```
pip install -r requirements-dev.txt
python -m pytest
```

No necesitan VPN ni Windows. Si hay Chrome instalado, una parte prueba los selectores en Chrome headless contra HTML que imita las pantallas de SIAC; sin Chrome, esa parte se salta.

## Problemas comunes

| Síntoma | Qué hacer |
|---|---|
| El navegador no abre o falla al arrancar. | Cierra cualquier Chrome/Edge que esté usando la carpeta `perfiles/` y revisa que no haya un `chromedriver.exe` viejo en el PATH. |
| La ventana de credenciales queda incompleta o rechaza la contraseña. | Prueba con `verificar-password`; si la contraseña es correcta, sube `pausa_tecla` y `espera_foco`. |
| "No se pudo conectar" o el portal no carga. | La VPN no está conectada. |
| Muchos `FALLO` seguidos. | Sube los `Tiempos` y revisa el motivo en la columna `detalle`; con `--debug` se ve qué encuentra el robot. |

## Seguridad

- La contraseña **nunca** va en el código: se guarda en el Administrador de credenciales de Windows (`keyring`).
- `datos/` tiene datos personales de clientes y `perfiles/` tiene sesiones abiertas. Ambas están en `.gitignore`: no las subas al repositorio.
