"""Modelos del dominio: los contratos que comparten los dos flujos.

Archivo COMPARTIDO (fase 0). Agregar campos con valor por defecto es retrocompatible;
renombrar o quitar campos rompe el trabajo del otro integrante.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    Conservacion,
    Dictamen,
    EstadoCaso,
    EstadoDonativo,
    EstadoPronostico,
    Rol,
    TipoAlimento,
    TipoCaso,
    TipoEntradaBitacora,
)


def ahora() -> datetime:
    """Hora local sin microsegundos (el MVP corre en una sola zona horaria)."""
    return datetime.now().replace(microsecond=0)


def nuevo_id() -> str:
    return uuid4().hex[:8]


# ---------------------------------------------------------------- participantes


class Ubicacion(BaseModel):
    lat: float
    lon: float
    direccion: str = ""


class Participante(BaseModel):
    id: str = Field(default_factory=nuevo_id)
    nombre: str
    rol: Rol
    ubicacion: Ubicacion
    telefono: str = ""
    pin_hash: str = ""  # PBKDF2 del PIN de inicio de sesión; nunca el PIN en claro


class Donante(Participante):
    rol: Literal[Rol.DONANTE] = Rol.DONANTE
    tipo_comercio: str = "fonda"
    hora_cierre: str = "20:00"  # HH:MM


class Receptor(Participante):
    rol: Literal[Rol.RECEPTOR] = Rol.RECEPTOR
    tipos_aceptados: list[TipoAlimento] = Field(default_factory=lambda: list(TipoAlimento))
    capacidad_kg_dia: float = 50.0
    tiene_refrigeracion: bool = False
    hora_apertura: str = "08:00"  # HH:MM
    hora_cierre: str = "20:00"  # HH:MM
    personas_atendidas: int = 50


class Recolector(Participante):
    rol: Literal[Rol.RECOLECTOR] = Rol.RECOLECTOR
    zona: str = ""
    transporte: str = "auto"
    disponible: bool = True


class Actor(BaseModel):
    """Quién hace una operación. Lo crea la sesión; los servicios lo validan contra la base."""

    model_config = ConfigDict(frozen=True)

    rol: Rol
    participante_id: str | None = None  # None solo para el coordinador


ParticipanteConcreto = Union[Donante, Receptor, Recolector]
CLASE_POR_ROL: dict[Rol, type[Participante]] = {
    Rol.DONANTE: Donante,
    Rol.RECEPTOR: Receptor,
    Rol.RECOLECTOR: Recolector,
}


# -------------------------------------------------------------------- donativos


class Alimento(BaseModel):
    nombre: str
    cantidad: float = Field(gt=0)
    unidad: str = "pieza"  # kg, pieza, porcion, litro, charola, bolsa, caja
    tipo: TipoAlimento = TipoAlimento.OTRO
    conservacion: Conservacion = Conservacion.DESCONOCIDA
    kg_estimados: float = Field(default=0.0, ge=0)  # lo calcula código, nunca el LLM
    observaciones: str = ""


class DictamenInocuidad(BaseModel):
    dictamen: Dictamen
    motivo: str
    condiciones: list[str] = []
    vida_util_horas: float | None = None
    requiere_refrigeracion: bool = False
    reglas_citadas: list[str] = []  # p. ej. "NOM-251-SSA1-2009, numeral 7.3.3"
    requiere_revision: bool = False  # el coordinador debe revisarlo (caso INOCUIDAD_DUDOSA)


class Asignacion(BaseModel):
    receptor_id: str | None = None  # None = nadie compatible; lo revisa el coordinador
    puntaje: float = 0.0
    justificacion: str = ""
    alternativas: list[str] = []  # ids de los siguientes mejores receptores
    aceptada: bool = False
    requiere_coordinador: bool = False
    fecha: datetime = Field(default_factory=ahora)


class Donativo(BaseModel):
    id: str = Field(default_factory=nuevo_id)
    donante_id: str
    texto_original: str
    alimentos: list[Alimento]
    hora_preparacion: datetime | None = None
    recoger_antes_de: datetime | None = None
    estado: EstadoDonativo = EstadoDonativo.PUBLICADO
    dictamen: DictamenInocuidad | None = None
    asignacion: Asignacion | None = None
    recolector_id: str | None = None
    receptores_descartados: list[str] = []  # receptores que ya lo rechazaron
    creado: datetime = Field(default_factory=ahora)
    actualizado: datetime = Field(default_factory=ahora)

    @property
    def kg_totales(self) -> float:
        return round(sum(a.kg_estimados for a in self.alimentos), 2)

    @property
    def receptor_id(self) -> str | None:
        return self.asignacion.receptor_id if self.asignacion else None

    def resumen(self) -> str:
        return ", ".join(f"{a.cantidad:g} {a.unidad} de {a.nombre}" for a in self.alimentos)


# --------------------------------------------------------------------- bitácora


class EntradaBitacora(BaseModel):
    """CAR-11: un paso del razonamiento de un agente."""

    id: str = Field(default_factory=nuevo_id)
    donativo_id: str | None = None
    agente: str
    paso: int = 0
    tipo: TipoEntradaBitacora
    contenido: str
    datos: dict = {}
    fecha: datetime = Field(default_factory=ahora)


# ------------------------------------------------- entradas y salidas de agentes


class SolicitudInterpretacion(BaseModel):
    """Entrada del Agente Intérprete."""

    texto: str
    donante: Donante
    donativo_id: str = Field(default_factory=nuevo_id)  # también es el id de traza


class ResultadoInterpretacion(BaseModel):
    """Salida del Agente Intérprete."""

    completo: bool
    alimentos: list[Alimento] = []
    hora_preparacion: datetime | None = None
    recoger_antes_de: datetime | None = None
    preguntas: list[str] = []  # si completo es False, lo que hay que preguntarle al donante
    alertas: list[str] = []  # códigos de seguridad: posible_inyeccion, conservacion_corregida, ...


class SolicitudAsignacion(BaseModel):
    """Entrada del Agente Asignador."""

    donativo: Donativo
    donante: Donante
    receptores: list[Receptor]


# ------------------------------------------- eventos, avisos, casos y pronósticos


class EventoDonativo(BaseModel):
    """Lo que publica el ciclo de vida en el bus de eventos (patrón Observer)."""

    donativo_id: str
    evento: str  # valor de Evento, o "publicar" / "aceptar"
    anterior: EstadoDonativo | None = None
    nuevo: EstadoDonativo
    motivo: str = ""
    actor: Actor | None = None
    fecha: datetime = Field(default_factory=ahora)


class Aviso(BaseModel):
    """CAR-06: notificación dentro de la app para un participante o para la coordinación."""

    id: str = Field(default_factory=nuevo_id)
    rol: Rol  # rol del destinatario
    destinatario_id: str | None = None  # None = toda la coordinación
    donativo_id: str | None = None
    titulo: str
    mensaje: str
    leido: bool = False
    fecha: datetime = Field(default_factory=ahora)


class CasoEscalado(BaseModel):
    """CAR-10: caso en la bandeja del coordinador."""

    id: str = Field(default_factory=nuevo_id)
    tipo: TipoCaso
    donativo_id: str | None = None
    motivo: str
    emisor: str  # "Intérprete", "Inocuidad", "Asignador", "Distribución"
    estado: EstadoCaso = EstadoCaso.ABIERTO
    resolucion: str = ""
    creado: datetime = Field(default_factory=ahora)
    resuelto: datetime | None = None


class Pronostico(BaseModel):
    """CAR-07: excedente probable de un donante en un día. Kilos y confianza los calcula código."""

    id: str = Field(default_factory=nuevo_id)
    donante_id: str
    fecha: date
    tipo: TipoAlimento
    descripcion: str
    kg_esperados: float
    confianza: float
    mensaje: str
    receptor_sugerido_id: str | None = None  # pre-reserva por puntuación determinista
    estado: EstadoPronostico = EstadoPronostico.VIGENTE
    creado: datetime = Field(default_factory=ahora)
