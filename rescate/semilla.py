"""Carga de los datos de demostración (datos/semilla.json).

Archivo COMPARTIDO (fase 0). El CONTENIDO de datos/semilla.json es de Alejandro.
"""
from __future__ import annotations

import json
from pathlib import Path

from rescate.dominio.enums import Rol
from rescate.dominio.modelos import CLASE_POR_ROL, Participante
from rescate.persistencia.repositorios import RepositorioParticipantes

SECCIONES = {"donantes": Rol.DONANTE, "receptores": Rol.RECEPTOR, "recolectores": Rol.RECOLECTOR}


def leer_semilla(ruta: Path) -> list[Participante]:
    """Lee y valida el archivo. Lanza un error de Pydantic si algún registro está mal."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    participantes: list[Participante] = []
    for seccion, rol in SECCIONES.items():
        for registro in datos.get(seccion, []):
            participantes.append(CLASE_POR_ROL[rol].model_validate(registro))
    return participantes


def cargar_semilla(repositorio: RepositorioParticipantes, ruta: Path) -> int:
    participantes = leer_semilla(ruta)
    for p in participantes:
        repositorio.guardar(p)
    return len(participantes)
