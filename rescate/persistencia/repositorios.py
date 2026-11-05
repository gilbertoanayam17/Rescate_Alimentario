"""Patrón Repository: interfaces de acceso a datos y su implementación en DuckDB.

El resto del sistema depende de las interfaces (RepositorioParticipantes, etc.),
no de DuckDB. Cada operación usa su propio cursor porque Streamlit atiende
sesiones en hilos distintos.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta

import duckdb

from rescate.dominio.enums import EstadoDonativo, Evento, Rol
from rescate.dominio.modelos import (
    CLASE_POR_ROL,
    Donante,
    Donativo,
    EntradaBitacora,
    Participante,
    Receptor,
    Recolector,
    ahora,
)

# ------------------------------------------------------------------- interfaces


class RepositorioParticipantes(ABC):
    @abstractmethod
    def guardar(self, participante: Participante) -> None: ...

    @abstractmethod
    def obtener(self, participante_id: str) -> Participante | None: ...

    @abstractmethod
    def listar(self, rol: Rol | None = None) -> list[Participante]: ...

    @abstractmethod
    def eliminar(self, participante_id: str) -> None: ...

    def donantes(self) -> list[Donante]:
        return self.listar(Rol.DONANTE)  # type: ignore[return-value]

    def receptores(self) -> list[Receptor]:
        return self.listar(Rol.RECEPTOR)  # type: ignore[return-value]

    def recolectores(self) -> list[Recolector]:
        return self.listar(Rol.RECOLECTOR)  # type: ignore[return-value]

    def vacio(self) -> bool:
        return not self.listar()


class RepositorioDonativos(ABC):
    @abstractmethod
    def guardar(self, donativo: Donativo) -> None: ...

    @abstractmethod
    def obtener(self, donativo_id: str) -> Donativo | None: ...

    @abstractmethod
    def listar(self, estado: EstadoDonativo | None = None) -> list[Donativo]: ...

    @abstractmethod
    def registrar_transicion(
        self,
        donativo_id: str,
        anterior: EstadoDonativo | None,
        nuevo: EstadoDonativo,
        evento: Evento | str,
        motivo: str = "",
    ) -> None: ...

    @abstractmethod
    def historial(self, donativo_id: str) -> list[dict]: ...

    # Consultas derivadas (comunes a cualquier implementación)
    def de_donante(self, donante_id: str) -> list[Donativo]:
        return [d for d in self.listar() if d.donante_id == donante_id]

    def de_receptor(self, receptor_id: str) -> list[Donativo]:
        return [d for d in self.listar() if d.receptor_id == receptor_id]

    def de_recolector(self, recolector_id: str) -> list[Donativo]:
        return [d for d in self.listar() if d.recolector_id == recolector_id]

    def kg_asignados(self, receptor_id: str, dia: date | None = None) -> float:
        """Kg ya comprometidos con un receptor en un día (para su capacidad)."""
        dia = dia or ahora().date()
        activos = {EstadoDonativo.ASIGNADO, EstadoDonativo.EN_RECOLECCION, EstadoDonativo.ENTREGADO}
        return round(
            sum(
                d.kg_totales
                for d in self.de_receptor(receptor_id)
                if d.estado in activos and d.asignacion and d.asignacion.fecha.date() == dia
            ),
            2,
        )

    def recibidos_ultimos_dias(self, receptor_id: str, dias: int = 7) -> list[Donativo]:
        """Donativos entregados a un receptor en los últimos `dias` (para equidad)."""
        desde = ahora() - timedelta(days=dias)
        return [
            d
            for d in self.de_receptor(receptor_id)
            if d.estado == EstadoDonativo.ENTREGADO and d.actualizado >= desde
        ]


class RepositorioBitacora(ABC):
    @abstractmethod
    def agregar(self, entrada: EntradaBitacora) -> None: ...

    @abstractmethod
    def de_donativo(self, donativo_id: str) -> list[EntradaBitacora]: ...

    @abstractmethod
    def recientes(self, limite: int = 200) -> list[EntradaBitacora]: ...


# --------------------------------------------------------- implementación DuckDB


class _BaseDuckDB:
    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con

    def _ejecutar(self, sql: str, parametros: list | None = None) -> list[tuple]:
        cursor = self._con.cursor()
        try:
            cursor.execute(sql, parametros or [])
            try:
                return cursor.fetchall()
            except duckdb.Error:
                return []  # sentencias sin resultado (INSERT, DELETE)
        finally:
            cursor.close()


class ParticipantesDuckDB(_BaseDuckDB, RepositorioParticipantes):
    def guardar(self, participante: Participante) -> None:
        self._ejecutar(
            "INSERT OR REPLACE INTO participantes VALUES (?, ?, ?, ?)",
            [participante.id, participante.rol.value, participante.nombre, participante.model_dump_json()],
        )

    def obtener(self, participante_id: str) -> Participante | None:
        filas = self._ejecutar("SELECT rol, datos FROM participantes WHERE id = ?", [participante_id])
        return _a_participante(*filas[0]) if filas else None

    def listar(self, rol: Rol | None = None) -> list[Participante]:
        if rol is None:
            filas = self._ejecutar("SELECT rol, datos FROM participantes ORDER BY rol, nombre")
        else:
            filas = self._ejecutar(
                "SELECT rol, datos FROM participantes WHERE rol = ? ORDER BY nombre", [rol.value]
            )
        return [_a_participante(r, d) for r, d in filas]

    def eliminar(self, participante_id: str) -> None:
        self._ejecutar("DELETE FROM participantes WHERE id = ?", [participante_id])


class DonativosDuckDB(_BaseDuckDB, RepositorioDonativos):
    def guardar(self, donativo: Donativo) -> None:
        self._ejecutar(
            "INSERT OR REPLACE INTO donativos VALUES (?, ?, ?, ?, ?, ?)",
            [
                donativo.id,
                donativo.donante_id,
                donativo.estado.value,
                donativo.model_dump_json(),
                donativo.creado,
                donativo.actualizado,
            ],
        )

    def obtener(self, donativo_id: str) -> Donativo | None:
        filas = self._ejecutar("SELECT datos FROM donativos WHERE id = ?", [donativo_id])
        return Donativo.model_validate_json(filas[0][0]) if filas else None

    def listar(self, estado: EstadoDonativo | None = None) -> list[Donativo]:
        if estado is None:
            filas = self._ejecutar("SELECT datos FROM donativos ORDER BY creado DESC")
        else:
            filas = self._ejecutar(
                "SELECT datos FROM donativos WHERE estado = ? ORDER BY creado DESC", [estado.value]
            )
        return [Donativo.model_validate_json(f[0]) for f in filas]

    def registrar_transicion(
        self,
        donativo_id: str,
        anterior: EstadoDonativo | None,
        nuevo: EstadoDonativo,
        evento: Evento | str,
        motivo: str = "",
    ) -> None:
        self._ejecutar(
            "INSERT INTO historial_estados VALUES (?, ?, ?, ?, ?, ?)",
            [
                donativo_id,
                anterior.value if anterior else None,
                nuevo.value,
                evento.value if isinstance(evento, Evento) else evento,
                motivo,
                datetime.now(),
            ],
        )

    def historial(self, donativo_id: str) -> list[dict]:
        filas = self._ejecutar(
            "SELECT anterior, nuevo, evento, motivo, fecha FROM historial_estados "
            "WHERE donativo_id = ? ORDER BY fecha",
            [donativo_id],
        )
        return [
            {"anterior": a, "nuevo": n, "evento": e, "motivo": m, "fecha": f} for a, n, e, m, f in filas
        ]


class BitacoraDuckDB(_BaseDuckDB, RepositorioBitacora):
    def agregar(self, entrada: EntradaBitacora) -> None:
        self._ejecutar(
            "INSERT INTO bitacora VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                entrada.id,
                entrada.donativo_id,
                entrada.agente,
                entrada.paso,
                entrada.tipo.value,
                entrada.contenido,
                json.dumps(entrada.datos, ensure_ascii=False, default=str),
                entrada.fecha,
            ],
        )

    def de_donativo(self, donativo_id: str) -> list[EntradaBitacora]:
        filas = self._ejecutar(
            "SELECT id, donativo_id, agente, paso, tipo, contenido, datos, fecha FROM bitacora "
            "WHERE donativo_id = ? ORDER BY fecha, paso",
            [donativo_id],
        )
        return [_a_entrada(f) for f in filas]

    def recientes(self, limite: int = 200) -> list[EntradaBitacora]:
        filas = self._ejecutar(
            "SELECT id, donativo_id, agente, paso, tipo, contenido, datos, fecha FROM bitacora "
            "ORDER BY fecha DESC, paso DESC LIMIT ?",
            [limite],
        )
        return [_a_entrada(f) for f in filas]


def _a_participante(rol: str, datos: str) -> Participante:
    return CLASE_POR_ROL[Rol(rol)].model_validate_json(datos)


def _a_entrada(fila: tuple) -> EntradaBitacora:
    id_, donativo_id, agente, paso, tipo, contenido, datos, fecha = fila
    return EntradaBitacora(
        id=id_,
        donativo_id=donativo_id,
        agente=agente,
        paso=paso or 0,
        tipo=tipo,
        contenido=contenido,
        datos=json.loads(datos) if datos else {},
        fecha=fecha,
    )
