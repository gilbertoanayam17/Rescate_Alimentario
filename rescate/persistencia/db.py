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
        actualizado TIMESTAMP
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
]


def conectar(ruta: str | Path) -> duckdb.DuckDBPyConnection:
    """Abre (o crea) la base y asegura que existan las tablas. Usa ':memory:' en pruebas."""
    ruta = str(ruta)
    if ruta != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(ruta)
    for sql in TABLAS:
        con.execute(sql)
    return con
