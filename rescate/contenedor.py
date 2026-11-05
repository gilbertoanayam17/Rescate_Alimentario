"""Raíz de composición: el único lugar donde se crean y conectan las piezas.

Archivo COMPARTIDO (fase 0). Cada integrante cambia SUS clases, no este archivo:
las fábricas `crear_base_conocimiento` (Gilberto) y los constructores de los agentes
ya están conectados aquí.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rescate.agentes.asignador import AgenteAsignador
from rescate.agentes.inocuidad import AgenteInocuidad
from rescate.agentes.interprete import AgenteInterprete
from rescate.bitacora import Bitacora
from rescate.config import Configuracion, cargar_configuracion
from rescate.llm.cliente import ClienteLLM
from rescate.llm.falso import ClienteLLMFalso
from rescate.llm.ollama_cliente import ClienteOllama
from rescate.orquestador import Orquestador
from rescate.persistencia.db import conectar
from rescate.persistencia.repositorios import BitacoraDuckDB, DonativosDuckDB, ParticipantesDuckDB
from rescate.rag.base_conocimiento import crear_base_conocimiento
from rescate.semilla import cargar_semilla
from rescate.servicios import ServicioDonativos


def construir_servicio(
    config: Configuracion | None = None,
    llm: ClienteLLM | None = None,
    ruta_db: str | Path | None = None,
    cargar_datos_semilla: bool = True,
) -> ServicioDonativos:
    config = config or cargar_configuracion()
    if ruta_db is not None:
        config = replace(config, ruta_db=Path(ruta_db) if ruta_db != ":memory:" else ruta_db)

    con = conectar(config.ruta_db)
    participantes = ParticipantesDuckDB(con)
    donativos = DonativosDuckDB(con)
    bitacora = Bitacora(BitacoraDuckDB(con))

    if llm is None:
        llm = (
            ClienteLLMFalso()
            if config.usar_llm_falso
            else ClienteOllama(config.modelo, config.modelo_embeddings, config.ollama_url)
        )

    orquestador = Orquestador(
        interprete=AgenteInterprete(llm, bitacora),
        inocuidad=AgenteInocuidad(llm, bitacora, crear_base_conocimiento(config, llm)),
        asignador=AgenteAsignador(llm, bitacora, participantes, donativos),
    )
    servicio = ServicioDonativos(orquestador, participantes, donativos, bitacora, llm)

    if cargar_datos_semilla and participantes.vacio() and Path(config.ruta_semilla).exists():
        cargar_semilla(participantes, config.ruta_semilla)
    return servicio
