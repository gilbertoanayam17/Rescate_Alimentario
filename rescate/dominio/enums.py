"""Enumeraciones del dominio de Rescate Alimentario.

Archivo COMPARTIDO (fase 0). Agregar valores es retrocompatible; renombrar o quitar no.
"""
from enum import Enum


class Rol(str, Enum):
    DONANTE = "donante"
    RECEPTOR = "receptor"
    RECOLECTOR = "recolector"
    COORDINADOR = "coordinador"


class TipoAlimento(str, Enum):
    PREPARADO = "preparado"  # guisados y comida cocinada lista para servir
    PANADERIA = "panaderia"  # pan dulce, bolillos, tortillas
    FRUTA_VERDURA = "fruta_verdura"
    LACTEO = "lacteo"
    CARNE_PESCADO = "carne_pescado"  # carne, pollo o pescado crudos
    ABARROTE = "abarrote"  # no perecederos: arroz crudo, frijol, enlatados
    BEBIDA = "bebida"
    OTRO = "otro"


#: Tipos que se echan a perder rápido sin control de temperatura.
PERECEDEROS = {TipoAlimento.PREPARADO, TipoAlimento.LACTEO, TipoAlimento.CARNE_PESCADO}


class Conservacion(str, Enum):
    AMBIENTE = "ambiente"
    REFRIGERADO = "refrigerado"
    CONGELADO = "congelado"
    CALIENTE = "caliente"
    DESCONOCIDA = "desconocida"


class Dictamen(str, Enum):
    APTO = "apto"
    APTO_CON_CONDICIONES = "apto_con_condiciones"
    NO_APTO = "no_apto"

    @property
    def severidad(self) -> int:
        """0 = apto, 1 = apto con condiciones, 2 = no apto."""
        return ["apto", "apto_con_condiciones", "no_apto"].index(self.value)

    @staticmethod
    def mas_estricto(a: "Dictamen", b: "Dictamen") -> "Dictamen":
        """Devuelve el dictamen más restrictivo de los dos (la inocuidad manda)."""
        return a if a.severidad >= b.severidad else b


class EstadoDonativo(str, Enum):
    PUBLICADO = "publicado"
    EVALUADO = "evaluado"
    ASIGNADO = "asignado"
    EN_RECOLECCION = "en_recoleccion"
    ENTREGADO = "entregado"
    RECHAZADO = "rechazado"  # no apto para donarse
    EXPIRADO = "expirado"
    CANCELADO = "cancelado"


class Evento(str, Enum):
    """Eventos que mueven a un donativo de un estado a otro (CAR-05)."""

    EVALUAR_APTO = "evaluar_apto"
    EVALUAR_NO_APTO = "evaluar_no_apto"
    ASIGNAR = "asignar"
    LIBERAR = "liberar"  # el receptor rechaza la asignación
    INICIAR_RECOLECCION = "iniciar_recoleccion"
    ENTREGAR = "entregar"
    EXPIRAR = "expirar"
    CANCELAR = "cancelar"


class TipoEntradaBitacora(str, Enum):
    PENSAMIENTO = "pensamiento"
    ACCION = "accion"
    OBSERVACION = "observacion"
    RESULTADO = "resultado"
    ERROR = "error"
