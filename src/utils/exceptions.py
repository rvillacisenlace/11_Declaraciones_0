"""Excepciones del proyecto. Cada una implica una decision distinta del lote."""


class ZeroError(Exception):
    """Base de los errores controlados."""


class ConfigError(ZeroError):
    """Falta o es invalida la configuracion."""


class LoginError(ZeroError):
    """No hay sesion valida. Sin reintento automatico."""


class CredentialsRejected(ZeroError):
    """El portal rechazo credenciales. Sin reintento: detiene el lote."""


class ContadorRechazado(CredentialsRejected):
    """El portal rechazo al contador que firma. Afecta a TODOS los fideicomisos: detiene el lote."""


class CaptchaRejected(ZeroError):
    """Captcha rechazado. Reintentable con tope."""


class PortalChanged(ZeroError):
    """El portal no respondio como se esperaba (selector o pantalla distinta)."""


class PasoNoMapeado(ZeroError):
    """Pantalla o caso que aun no esta implementado: se detiene, no se improvisa."""


class ObligacionNoDisponible(ZeroError):
    """El contribuyente no tiene esa obligacion (p. ej. IVA semestral)."""


class PeriodoNoCoincide(ZeroError):
    """El periodo calculado no coincide con lo que muestra el portal: revision manual."""


class AlreadyDeclared(ZeroError):
    """Ya existe declaracion del periodo. No es un fallo: se registra como 'ya hecho'."""


class ComprobanteInvalido(ZeroError):
    """El comprobante descargado no corresponde a lo esperado (otro RUC, otro periodo, con valor a pagar...).
    La declaracion pudo haberse enviado: exige revision manual en el SRI."""


class EnvioIncierto(ZeroError):
    """Se pulso Aceptar pero no se pudo confirmar el resultado: la declaracion pudo haberse enviado.
    Nunca se reintenta; exige revision manual en el SRI."""


class RecargosInesperados(ZeroError):
    """El portal calculo interes o multa: la declaracion no seria en cero. No se envia."""