"""Todos los selectores en un solo lugar. Por texto/ids estables, nunca por indice de lista."""

OBLIGACION_IVA = "2011"  # codigo; el texto varia (doble espacio, guiones), el codigo no
OBLIGACION_WIDGET = '[id="frmFlujoDeclaracion:somObligacion"]'  # raiz del selectonemenu (id del li sin el _N)
OBLIGACION_ETIQUETA = ".ui-selectonemenu-label"
PERIODO_CAMPO = '[id="frmFlujoDeclaracion:calPeriodo"]'
MES_TABLA = "table.month-picker-month-table"
MES_RESALTADO = "a.ui-state-highlight"
BOTON_SIGUIENTE = '[id="frmFlujoDeclaracion:btnObligacionSiguiente"]'  # id estable; el portal lo vuelve a pintar por ajax
MENU_FORMULARIO_IVA = "Formulario de IVA"  # mosaico de la pagina publica tras el login


def opcion_obligacion(codigo: str) -> str:
    return f'li.ui-selectonemenu-item[data-label^="{codigo}"]'


# Login (tomados de Archivist; VERIFICAR en la pantalla de login de declaraciones)
LOGIN_USUARIO = "#usuario"  # campo del RUC
LOGIN_CLAVE = "#password"
LOGIN_ENVIAR = "#kc-login"
LOGIN_RUTA = "/auth/realms/"  # mientras la URL contenga esto, sigue en el login

# Pregunta "Requiere informar valores": los ids (j_idt975, repeatCuestionario:4) son generados y cambian; se busca por texto
PREGUNTA_FILA = "div.respuestas-perfilamiento"
PREGUNTA_VALORES = "Requiere informar valores"
DIALOGO_MENSAJES = '[id="frmFlujoDeclaracion:dialogoMensajesPersonalizados"]'
BOTON_PERFILADOR_SIGUIENTE = '[id="frmFlujoDeclaracion:btnPerfiladorSiguiente"]'  # Siguiente del cuestionario