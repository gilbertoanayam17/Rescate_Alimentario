"""Raíz de composición: el único lugar donde se crean y conectan las piezas.

Archivo COMPARTIDO. `construir_servicios()` es lo que usa la app; `construir_aplicacion()` además
expone los repositorios y el orquestador para las pruebas y los scripts.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from rescate.agentes.asignador import AgenteAsignador
from rescate.agentes.inocuidad import AgenteInocuidad
from rescate.agentes.interprete import AgenteInterprete
from rescate.agentes.logistico import AgenteLogistico
from rescate.agentes.predictor import AgentePredictor
from rescate.bitacora import Bitacora
from rescate.config import Configuracion, cargar_configuracion
from rescate.dominio.modelos import ahora
from rescate.llm.cliente import ClienteLLM
from rescate.llm.falso import ClienteLLMFalso
from rescate.llm.ollama_cliente import ClienteOllama
from rescate.mediador import MediadorCasos
from rescate.orquestador import Orquestador
from rescate.persistencia.db import conectar
from rescate.persistencia.repositorios import (
    AvisosDuckDB,
    BitacoraDuckDB,
    CasosDuckDB,
    DonativosDuckDB,
    ParticipantesDuckDB,
    PronosticosDuckDB,
)
from rescate.rag.base_conocimiento import crear_base_conocimiento
from rescate.semilla import cargar_semilla
from rescate.servicios import (
    ServicioCasos,
    ServicioDistribucion,
    ServicioNotificaciones,
    ServicioParticipantes,
    ServicioPrediccion,
    ServicioPublicacion,
    ServicioReportes,
    Servicios,
)
from rescate.servicios.ciclo_vida import CicloDeVida
from rescate.servicios.eventos import BusEventos
from rescate.servicios.notificaciones import AvisosEnApp, NotificadorEstados


@dataclass(frozen=True)
class Repositorios:
    participantes: ParticipantesDuckDB
    donativos: DonativosDuckDB
    avisos: AvisosDuckDB
    casos: CasosDuckDB
    pronosticos: PronosticosDuckDB


@dataclass(frozen=True)
class Aplicacion:
    servicios: Servicios
    repos: Repositorios
    bitacora: Bitacora
    orquestador: Orquestador
    bus: BusEventos
    mediador: MediadorCasos
    llm: ClienteLLM


def construir_aplicacion(
    config: Configuracion | None = None,
    llm: ClienteLLM | None = None,
    ruta_db: str | Path | None = None,
    cargar_datos_semilla: bool = True,
    reloj: Callable[[], datetime] = ahora,
) -> Aplicacion:
    config = config or cargar_configuracion()
    if ruta_db is not None:
        config = replace(config, ruta_db=Path(ruta_db) if ruta_db != ":memory:" else ruta_db)

    con = conectar(config.ruta_db)
    repos = Repositorios(
        participantes=ParticipantesDuckDB(con),
        donativos=DonativosDuckDB(con),
        avisos=AvisosDuckDB(con),
        casos=CasosDuckDB(con),
        pronosticos=PronosticosDuckDB(con),
    )
    bitacora = Bitacora(BitacoraDuckDB(con))

    if llm is None:
        llm = (
            ClienteLLMFalso()
            if config.usar_llm_falso
            else ClienteOllama(config.modelo, config.modelo_embeddings, config.ollama_url)
        )

    orquestador = Orquestador(
        interprete=AgenteInterprete(llm, bitacora, reloj=reloj),
        inocuidad=AgenteInocuidad(llm, bitacora, crear_base_conocimiento(config, llm)),
        asignador=AgenteAsignador(llm, bitacora, repos.participantes, repos.donativos, reloj=reloj),
    )

    # Observer: el ciclo de vida publica; notificador y mediador escuchan.
    bus = BusEventos()
    canal = AvisosEnApp(repos.avisos)
    bus.suscribir(NotificadorEstados(canal, repos.participantes, repos.donativos))
    mediador = MediadorCasos(repos.casos, canal, bus, reloj=reloj)
    ciclo = CicloDeVida(repos.donativos, bus)

    servicios = Servicios(
        participantes=ServicioParticipantes(
            repos.participantes, repos.donativos, pin_coordinador=config.pin_coordinador
        ),
        publicacion=ServicioPublicacion(orquestador, repos.participantes, repos.donativos, ciclo, mediador),
        distribucion=ServicioDistribucion(
            orquestador,
            repos.participantes,
            repos.donativos,
            ciclo,
            mediador,
            logistico=AgenteLogistico(llm, bitacora),
            reloj=reloj,
        ),
        reportes=ServicioReportes(repos.participantes, repos.donativos, bitacora),
        notificaciones=ServicioNotificaciones(repos.avisos, repos.participantes),
        casos=ServicioCasos(repos.casos, reloj=reloj),
        prediccion=ServicioPrediccion(
            AgentePredictor(llm, bitacora),
            repos.participantes,
            repos.donativos,
            repos.pronosticos,
            canal,
            reloj=reloj,
        ),
        estado_llm=lambda: (
            f"LLM local: {llm.nombre_modelo}"
            if llm.disponible()
            else "Sin LLM: los agentes usan sus reglas de respaldo"
        ),
        correo_coordinacion=config.correo_coordinacion,
        telefono_coordinacion=config.telefono_coordinacion,
    )

    if cargar_datos_semilla and repos.participantes.vacio() and Path(config.ruta_semilla).exists():
        cargar_semilla(repos.participantes, config.ruta_semilla)
    return Aplicacion(servicios, repos, bitacora, orquestador, bus, mediador, llm)


def construir_servicios(
    config: Configuracion | None = None,
    llm: ClienteLLM | None = None,
    ruta_db: str | Path | None = None,
    cargar_datos_semilla: bool = True,
    reloj: Callable[[], datetime] = ahora,
) -> Servicios:
    """Lo que necesita la interfaz."""
    return construir_aplicacion(config, llm, ruta_db, cargar_datos_semilla, reloj).servicios
