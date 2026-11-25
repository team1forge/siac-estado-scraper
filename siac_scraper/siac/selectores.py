"""Textos y patrones con los que el robot reconoce las pantallas de SIAC.

Si SIAC cambia un título, un mensaje o una etiqueta, normalmente basta con ajustar este archivo.

Las expresiones regulares se aplican al título, la URL o el texto visible de la ventana, y
aceptan la palabra con y sin tilde (SIAC no es consistente).
"""
import re

# Ventana de SIAC Único (por título o URL)
VENTANA_SIAC = re.compile(r"siac", re.I)

# Popup "Consulta de Productos" que sale al presionar la lupa
POPUP_PRODUCTOS = re.compile(r"popup|consulta de productos", re.I)

# Popup "Consulta de Clientes": sale cuando el documento tiene varios clientes (RUC, Pasaporte...)
CONSULTA_CLIENTES = re.compile(r"consulta de clientes", re.I)

# Alerta "Usted no está autorizado para consultar este tipo de producto"
ALERTA = re.compile(r"no est[aá] autorizad|^\s*alerta\s*$", re.I | re.M)

# Tabla de servicios que solo dice "No existen datos"
SIN_DATOS = re.compile(r"no existen datos|no hay datos|sin datos|ning[uú]n dato", re.I)

# Título del detalle de líneas (ventana nueva o dentro del mismo popup)
DETALLE_LINEAS = re.compile(r"l[ií]neas asociadas", re.I)

# Productos fijos: su detalle suele fallar, así que se prefiere otra fila (ej. MOVIL)
PRODUCTO_FIJO = re.compile(r"hfc|ftth", re.I)

# Textos posibles del botón del desplegable de tipo de búsqueda
OPCIONES_BUSQUEDA = ("Teléfono", "Telefono", "Cuenta", "Customer Id", "ICCID", "Nombres",
                     "Documento Identidad", "Número de Recibo", "Razón Social")

# Panel "Datos del Cliente": campo del CSV -> etiquetas posibles en SIAC
# (en minúsculas y sin tildes; se comparan contra el texto exacto de la etiqueta)
ETIQUETAS_CLIENTE = {
    "cliente": ["cliente", "razon social", "nombres y apellidos"],
    "contacto": ["contacto"],
    "representante_legal": ["representante legal", "rep. legal"],
    "telefono": ["tel. referencia 1", "tel. referencia", "telefono referencia", "telefono"],
    "email": ["email", "e-mail", "correo", "correo electronico"],
}
