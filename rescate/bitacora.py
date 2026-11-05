"""CAR-11 Bitácora de razonamiento.

Cada agente anota aquí sus pensamientos, acciones (llamadas a herramientas o al LLM),
observaciones y resultado. La interfaz la muestra para que el razonamiento sea visible.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

from rescate.dominio.enums import TipoEntradaBitacora
from rescate.dominio.modelos import EntradaBitacora
from rescate.persistencia.repositorios import RepositorioBitacora


class Bitacora:
    def __init__(self, repositorio: RepositorioBitacora) -> None:
        self._repositorio = repositorio

    def registrar(
        self,
        agente: str,
        tipo: TipoEntradaBitacora,
        contenido: str,
        donativo_id: str | None = None,
        paso: int = 0,
        datos: dict | None = None,
    ) -> EntradaBitacora:
        entrada = EntradaBitacora(
            agente=agente,
            tipo=tipo,
            contenido=contenido,
            donativo_id=donativo_id,
            paso=paso,
            datos=datos or {},
        )
        self._repositorio.agregar(entrada)
        return entrada

    def de_donativo(self, donativo_id: str) -> list[EntradaBitacora]:
        return self._repositorio.de_donativo(donativo_id)

    def recientes(self, limite: int = 200) -> list[EntradaBitacora]:
        return self._repositorio.recientes(limite)
