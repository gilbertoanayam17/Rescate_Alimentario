"""Configuración leída del archivo .env (ver .env.example).

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

#: Perfiles de modelo de la sección 9.2 del documento de visión.
PERFILES = {
    "ligero": "gemma4:e4b",
    "completo": "gemma4:26b",
    "minimo": "gemma4:e2b",
}


@dataclass(frozen=True)
class Configuracion:
    perfil: str
    modelo: str
    modelo_embeddings: str
    ollama_url: str
    usar_llm_falso: bool
    ruta_db: Path
    ruta_semilla: Path
    ruta_conocimiento: Path
    ruta_indice: Path


def cargar_configuracion() -> Configuracion:
    perfil = os.getenv("PERFIL_MODELO", "ligero").strip().lower()
    return Configuracion(
        perfil=perfil,
        modelo=os.getenv("MODELO_LLM") or PERFILES.get(perfil, PERFILES["ligero"]),
        modelo_embeddings=os.getenv("MODELO_EMBEDDINGS", "nomic-embed-text"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        usar_llm_falso=os.getenv("USAR_LLM_FALSO", "0").strip() in {"1", "true", "si", "sí"},
        ruta_db=RAIZ / os.getenv("RUTA_DB", "datos/rescate.duckdb"),
        ruta_semilla=RAIZ / "datos" / "semilla.json",
        ruta_conocimiento=RAIZ / "datos" / "conocimiento",
        ruta_indice=RAIZ / "datos" / "indice",
    )
