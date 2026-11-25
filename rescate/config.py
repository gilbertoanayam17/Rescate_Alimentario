"""Configuración leída del archivo .env (ver .env.example).

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from rescate.dominio.modelos import fijar_hora_demo

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
    pin_demo: str = "1234"  # PIN que reciben los participantes de la semilla sin PIN
    pin_coordinador: str = "0000"  # PIN de la sesión del coordinador
    hora_demo: str | None = None  # "HH:MM": el reloj de la app corre desde esa hora de hoy
    correo_coordinacion: str = ""  # contacto para pedir alta o PIN nuevo (pantalla de entrada)
    telefono_coordinacion: str = ""


def cargar_configuracion() -> Configuracion:
    """Lee .env y aplica la hora de demo (HORA_DEMO) al reloj de toda la app."""
    perfil = os.getenv("PERFIL_MODELO", "ligero").strip().lower()
    hora_demo = os.getenv("HORA_DEMO", "").strip() or None
    try:
        fijar_hora_demo(hora_demo)
    except ValueError as e:
        raise ValueError(f"HORA_DEMO debe tener el formato HH:MM (24 h); se leyó {hora_demo!r}.") from e
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
        pin_demo=os.getenv("PIN_DEMO", "1234").strip(),
        pin_coordinador=os.getenv("PIN_COORDINADOR", "0000").strip(),
        hora_demo=hora_demo,
        correo_coordinacion=os.getenv("CORREO_COORDINACION", "").strip(),
        telefono_coordinacion=os.getenv("TELEFONO_COORDINACION", "").strip(),
    )
