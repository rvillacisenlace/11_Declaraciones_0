"""Estados de una declaracion. Una declaracion = un fideicomiso en un periodo."""
from enum import Enum


class Estado(str, Enum):
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    PARCIAL = "parcial"  # el flujo se detuvo a proposito antes del final (--hasta); no se envio nada
    SIMULADO = "simulado"  # prueba completa hasta los datos del contador; no se envio nada
    DECLARADO = "declarado"  # reservado para el envio real (aun no implementado)
    YA_DECLARADO = "ya_declarado"
    OBLIGACION_NO_DISPONIBLE = "obligacion_no_disponible"  # p. ej. IVA semestral
    REVISION_MANUAL = "revision_manual"
    ERROR = "error"


# Estados de los que no se vuelve a pasar nunca: evitan declarar dos veces.
FINALES = frozenset({Estado.DECLARADO, Estado.YA_DECLARADO, Estado.OBLIGACION_NO_DISPONIBLE})
