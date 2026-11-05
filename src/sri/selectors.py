"""Todos los selectores en un solo lugar. Por texto/ids estables, nunca por indice de lista."""

OBLIGACION_IVA = "2011 DECLARACION DE IVA"
OBLIGACION_WIDGET = '[id="frmFlujoDeclaracion:somObligacion"]'  # raiz del selectonemenu (id del li sin el _N)
OBLIGACION_ETIQUETA = ".ui-selectonemenu-label"
MES_TABLA = "table.month-picker-month-table"
MES_RESALTADO = "a.ui-state-highlight"
BOTON_SIGUIENTE = "Siguiente"


def opcion_obligacion(nombre: str) -> str:
    return f'li.ui-selectonemenu-item[data-label="{nombre}"]'


# Login (tomados de Archivist; VERIFICAR en la pantalla de login de declaraciones)
LOGIN_USUARIO = "#usuario"  # campo del RUC
LOGIN_CLAVE = "#password"
LOGIN_ENVIAR = "#kc-login"
LOGIN_RUTA = "/auth/realms/"  # mientras la URL contenga esto, sigue en el login