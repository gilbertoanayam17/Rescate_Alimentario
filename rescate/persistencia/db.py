"""Conexión a DuckDB y esquema de tablas.

Los objetos del dominio se guardan como JSON (columna `datos`) para no acoplar el
esquema SQL a cada campo; las columnas extra sirven para filtrar rápido.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

TABLAS = [
    """CREATE TABLE IF NOT EXISTS participantes (
        id VARCHAR PRIMARY KEY,
        rol VARCHAR NOT NULL,
        nombre VARCHAR NOT NULL,
        datos VARCHAR NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS donativos (
        id VARCHAR PRIMARY KEY,
        donante_id VARCHAR NOT NULL,
        estado VARCHAR NOT NULL,
        datos VARCHAR NOT NULL,
        creado TIMESTAMP,
        actualizado TIMESTAMP,
        receptor_id VARCHAR,
        recolector_id VARCHAR,
        kg_totales DOUBLE
    )""",
    """CREATE TABLE IF NOT EXISTS historial_estados (
        donativo_id VARCHAR NOT NULL,
        anterior VARCHAR,
        nuevo VARCHAR NOT NULL,
        evento VARCHAR NOT NULL,
        motivo VARCHAR,
        fecha TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS bitacora (
        id VARCHAR PRIMARY KEY,
        donativo_id VARCHAR,
        agente VARCHAR NOT NULL,
        paso INTEGER,
        tipo VARCHAR NOT NULL,
        contenido VARCHAR NOT NULL,
        datos VARCHAR,
        fecha TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS avisos (
        id VARCHAR PRIMARY KEY,
        rol VARCHAR NOT NULL,
        destinatario_id VARCHAR,
        donativo_id VARCHAR,
        leido BOOLEAN DEFAULT FALSE,
        datos VARCHAR NOT NULL,
        fecha TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS casos (
        id VARCHAR PRIMARY KEY,
        tipo VARCHAR NOT NULL,
        donativo_id VARCHAR,
        estado VARCHAR NOT NULL,
        datos VARCHAR NOT NULL,
        creado TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS pronosticos (
        id VARCHAR PRIMARY KEY,
        donante_id VARCHAR NOT NULL,
        fecha DATE NOT NULL,
        estado VARCHAR NOT NULL,
        receptor_sugerido_id VARCHAR,
        datos VARCHAR NOT NULL
    )""",
]

#: Columnas agregadas en la entrega final; las bases creadas antes las reciben aquí.
MIGRACIONES = [
    "ALTER TABLE donativos ADD COLUMN IF NOT EXISTS receptor_id VARCHAR",
    "ALTER TABLE donativos ADD COLUMN IF NOT EXISTS recolector_id VARCHAR",
    "ALTER TABLE donativos ADD COLUMN IF NOT EXISTS kg_totales DOUBLE",
]


def conectar(ruta: str | Path) -> duckdb.DuckDBPyConnection:
    """Abre (o crea) la base y asegura que existan las tablas. Usa ':memory:' en pruebas."""
    ruta = str(ruta)
    if ruta != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(ruta)
    for sql in TABLAS + MIGRACIONES:
        con.execute(sql)
    return con
