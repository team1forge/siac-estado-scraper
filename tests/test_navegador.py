"""Selectores y lectura de SIAC contra HTML local en Chrome headless (se saltan sin Chrome)."""
from selenium.webdriver.common.by import By

from siac_scraper.config import Tiempos
from siac_scraper.navegador.dom import buscar_en_frames, xpath_boton, xpath_opcion_menu
from siac_scraper.siac import popups
from siac_scraper.siac.busqueda import buscar_desplegable, seleccionar_tipo_busqueda
from siac_scraper.siac.detalle import _primer_numero
from siac_scraper.siac.ficha import leer_datos_cliente
from siac_scraper.siac.tablas import (esperar_primera_fila, leer_tablas, popup_sin_datos,
                                      tablas_sin_filas)

RAPIDO = Tiempos(**{k: 0.5 for k in Tiempos.__dataclass_fields__})

ENCABEZADO = ("<thead><tr><th>Producto</th><th>Cuenta</th><th>Total Activas</th>"
              "<th>Total No Activas</th></tr></thead>")


def _fila(producto, cuenta, activas, no_activas):
    return (f"<tr><td>{producto}</td><td>{cuenta}</td>"
            f"<td><a href=\"javascript:OpenDetail('{cuenta}')\"><input disabled value='{activas}'></a></td>"
            f"<td><input disabled value='{no_activas}'></td></tr>")


def test_opcion_menu_clica_el_elemento_mas_interno(pagina):
    d = pagina("<table><tr><td id='menu'><a id='sivco' href='#'>SIVCO</a> "
               "<a id='siac' href='#'><span id='txt'>SIAC Único</span></a></td></tr></table>")
    el = d.find_elements(By.XPATH, xpath_opcion_menu("SIAC Unico"))
    assert [e.get_attribute("id") for e in el] == ["txt"]


def test_opcion_menu_dentro_de_iframe(pagina):
    d = pagina("<iframe srcdoc=\"<a id='x' href='#'>Siac Unico</a>\"></iframe>")
    el = buscar_en_frames(d, xpath_opcion_menu("SIAC Unico"), timeout=3)
    assert el is not None and el.get_attribute("id") == "x"
    d.switch_to.default_content()


def test_boton_aceptar_por_texto_o_value(pagina):
    d = pagina("<input type='button' id='b' value='ACEPTAR'>")
    assert d.find_element(By.XPATH, xpath_boton("aceptar")).get_attribute("id") == "b"


def test_tablas_con_encabezado_y_cuerpo_separados(pagina):
    d = pagina(f"<table>{ENCABEZADO}</table>"
               f"<table><tbody>{_fila('MOVIL', '111', '1.234', '0')}{_fila('Plan HFC', '222', '0', '3')}</tbody></table>")
    assert leer_tablas(d) == [("0|111", 1234, 0), ("0|222", 0, 3)]
    assert esperar_primera_fila(d, 2) == [("MOVIL", 1234, 0), ("Plan HFC", 0, 3)]


def test_popup_sin_datos(pagina):
    d = pagina(f"<table>{ENCABEZADO}<tbody><tr><td colspan='4'>No existen datos</td></tr></tbody></table>")
    assert leer_tablas(d) == []
    assert popup_sin_datos(d)


def test_tablas_sin_filas(pagina):
    d = pagina(f"<table>{ENCABEZADO}<tbody><tr><td></td><td></td><td></td><td></td></tr></tbody></table>")
    assert tablas_sin_filas(d)
    assert not popup_sin_datos(d)


def test_esperar_contenido_detecta_consulta_de_clientes(pagina):
    d = pagina("<h3>Consulta de Clientes</h3><table><tbody>"
               "<tr><td><input type='radio' name='c'></td><td>DNI</td><td>123</td></tr>"
               "<tr><td><input type='radio' name='c'></td><td>RUC</td><td>201</td></tr>"
               "</tbody></table><button onclick=\"document.body.innerHTML='<p>Consulta de Productos</p>'\">"
               "Seleccionar</button>")
    h = d.current_window_handle
    assert popups.esperar_contenido(d, h, (), RAPIDO)[0] == popups.CLIENTES
    assert popups.elegir_cliente(d, h, "RUC", RAPIDO) == h
    assert "Consulta de Productos" in d.find_element(By.TAG_NAME, "body").text


def test_esperar_contenido_detecta_alerta(pagina):
    d = pagina("<div><b>Alerta</b><p>Usted no está autorizado para consultar este tipo de producto</p></div>")
    contenido, mensaje, h = popups.esperar_contenido(d, d.current_window_handle, (), RAPIDO)
    assert contenido == popups.ALERTA
    assert mensaje.startswith("Usted no está autorizado")


def test_desplegable_de_busqueda(pagina):
    d = pagina("""
      <a class='dropdown-toggle' id='usuario'>Mi cuenta</a>
      <button class='dropdown-toggle' id='tipo' onclick="document.getElementById('menu').style.display='block'">Teléfono</button>
      <ul id='menu' style='display:none'>
        <li><a href='#' style='display:block' onclick="document.getElementById('tipo').innerText='Documento Identidad'">Documento Identidad</a></li>
      </ul>""")
    assert buscar_desplegable(d).get_attribute("id") == "tipo"
    seleccionar_tipo_busqueda(d, "Documento Identidad")
    assert d.find_element(By.ID, "tipo").text == "Documento Identidad"


def test_primer_numero_dentro_de_la_modal(pagina):
    d = pagina("<table><tbody><tr><td>999</td></tr></tbody></table>"
               "<div class='modal show' role='dialog'><h4>Líneas asociadas</h4>"
               "<table><tbody><tr><td>Activo</td><td><a id='n'>987 654 321</a></td></tr></tbody></table></div>")
    el, texto = _primer_numero(d)
    # el número de la modal (su celda o su enlace), no el 999 de la tabla de abajo
    assert texto == "987 654 321"
    assert el.find_elements(By.XPATH, "ancestor::div[@role='dialog']")


def test_leer_datos_cliente(pagina):
    d = pagina("""
      <table>
        <tr><td>Cliente</td><td>EMPRESA DEMO S.A.C. ...</td></tr>
        <tr><td>Contacto</td><td>Ana Pérez</td></tr>
        <tr><td>Rep. Legal</td><td>Luis Gómez</td></tr>
        <tr><td>Tel. Referencia 1</td><td>014445555</td></tr>
        <tr><td>E-mail</td><td>contacto@demo.pe</td></tr>
      </table>""")
    assert leer_datos_cliente(d, 2) == {
        "cliente": "EMPRESA DEMO S.A.C.", "contacto": "Ana Pérez", "representante_legal": "Luis Gómez",
        "telefono": "014445555", "email": "contacto@demo.pe"}


def test_cerrar_popup_vuelve_a_siac(chrome, tmp_path):
    siac = chrome.current_window_handle
    chrome.switch_to.new_window("window")
    popup = chrome.current_window_handle
    archivo = tmp_path / "p.html"
    archivo.write_text("<button onclick='window.close()'>Cerrar</button>", encoding="utf-8")
    chrome.get(archivo.as_uri())
    popups.cerrar_popup(chrome, popup, siac)
    assert popup not in chrome.window_handles
    assert chrome.current_window_handle == siac


def test_esperar_popup_ignora_ventanas_previas(chrome):
    antes = chrome.window_handles
    chrome.execute_script("window.open('about:blank', 'popup')")
    h = popups.esperar_popup(chrome, antes, 2)
    assert h is not None and h not in antes
    chrome.close()
    chrome.switch_to.window(antes[0])
