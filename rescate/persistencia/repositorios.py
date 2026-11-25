"""Patrón Repository: interfaces de acceso a datos y su implementación en DuckDB.

El resto del sistema depende de las interfaces (RepositorioParticipantes, etc.),
no de DuckDB. Cada operación usa su propio cursor porque Streamlit atiende
sesiones en hilos distintos.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from datetime import date, timedelta

import duckdb

from rescate.dominio.enums import EstadoCaso, EstadoDonativo, Evento, Rol, TipoCaso
from rescate.dominio.modelos import (
    CLASE_POR_ROL,
    Aviso,
    CasoEscalado,
    Donante,
    Donativo,
    EntradaBitacora,
    Participante,
    Pronostico,
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

    @abstractmethod
    def tomar_para_recoleccion(self, actualizado: Donativo) -> bool:
        """Guarda `actualizado` (ya EN_RECOLECCION y con recolector_id) solo si en la base sigue
        ASIGNADO y sin recolector. Devuelve True si lo tomó; False si otro voluntario ganó."""

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


class RepositorioAvisos(ABC):
    """Avisos dentro de la app (CAR-06)."""

    @abstractmethod
    def agregar(self, aviso: Aviso) -> None: ...

    @abstractmethod
    def de_destinatario(
        self, rol: Rol, destinatario_id: str | None, solo_no_leidos: bool = False, limite: int = 50
    ) -> list[Aviso]: ...

    @abstractmethod
    def marcar_leido(self, aviso_id: str, rol: Rol, destinatario_id: str | None) -> bool:
        """False si el aviso no existe o no es de ese destinatario."""


class RepositorioCasos(ABC):
    """Bandeja de casos escalados al coordinador (CAR-10)."""

    @abstractmethod
    def guardar(self, caso: CasoEscalado) -> None: ...

    @abstractmethod
    def obtener(self, caso_id: str) -> CasoEscalado | None: ...

    @abstractmethod
    def abiertos(self) -> list[CasoEscalado]: ...

    @abstractmethod
    def abierto_de(self, tipo: TipoCaso, donativo_id: str | None) -> CasoEscalado | None: ...

    @abstractmethod
    def de_donativo(self, donativo_id: str) -> list[CasoEscalado]: ...


class RepositorioPronosticos(ABC):
    """Pronósticos de excedentes (CAR-07)."""

    @abstractmethod
    def guardar(self, pronostico: Pronostico) -> None: ...

    @abstractmethod
    def obtener(self, pronostico_id: str) -> Pronostico | None: ...

    @abstractmethod
    def de_donante(self, donante_id: str, desde: date) -> list[Pronostico]: ...

    @abstractmethod
    def de_receptor(self, receptor_id: str, desde: date) -> list[Pronostico]: ...

    @abstractmethod
    def del_dia(self, fecha: date) -> list[Pronostico]: ...


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
    #: Un solo proceso atiende todas las sesiones de Streamlit: el candado evita que dos
    #: voluntarios tomen el mismo donativo entre la lectura y la escritura.
    _candado_toma = threading.Lock()

    def guardar(self, donativo: Donativo) -> None:
        self._ejecutar(
            "INSERT OR REPLACE INTO donativos (id, donante_id, estado, datos, creado, actualizado, "
            "receptor_id, recolector_id, kg_totales) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                donativo.id,
                donativo.donante_id,
                donativo.estado.value,
                donativo.model_dump_json(),
                donativo.creado,
                donativo.actualizado,
                donativo.receptor_id,
                donativo.recolector_id,
                donativo.kg_totales,
            ],
        )

    def tomar_para_recoleccion(self, actualizado: Donativo) -> bool:
        with self._candado_toma:
            try:
                filas = self._ejecutar(
                    "UPDATE donativos SET estado = ?, datos = ?, actualizado = ?, recolector_id = ? "
                    "WHERE id = ? AND estado = ? AND recolector_id IS NULL RETURNING id",
                    [
                        actualizado.estado.value,
                        actualizado.model_dump_json(),
                        actualizado.actualizado,
                        actualizado.recolector_id,
                        actualizado.id,
                        EstadoDonativo.ASIGNADO.value,
                    ],
                )
            except duckdb.TransactionException:
                return False  # otra transacción tocó la misma fila
        return bool(filas)

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
                ahora(),
            ],
        )

    def historial(self, donativo_id: str) -> list[dict]:
        filas = self._ejecutar(
            "SELECT anterior, nuevo, evento, motivo, fecha FROM historial_estados "
            "WHERE donativo_id = ? ORDER BY fecha, rowid",
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
            "WHERE donativo_id = ? ORDER BY fecha, rowid",  # rowid = orden de inserción
            [donativo_id],
        )
        return [_a_entrada(f) for f in filas]

    def recientes(self, limite: int = 200) -> list[EntradaBitacora]:
        filas = self._ejecutar(
            "SELECT id, donativo_id, agente, paso, tipo, contenido, datos, fecha FROM bitacora "
            "ORDER BY fecha DESC, rowid DESC LIMIT ?",
            [limite],
        )
        return [_a_entrada(f) for f in filas]


class AvisosDuckDB(_BaseDuckDB, RepositorioAvisos):
    def agregar(self, aviso: Aviso) -> None:
        self._ejecutar(
            "INSERT OR REPLACE INTO avisos (id, rol, destinatario_id, donativo_id, leido, datos, fecha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                aviso.id,
                aviso.rol.value,
                aviso.destinatario_id,
                aviso.donativo_id,
                aviso.leido,
                aviso.model_dump_json(),
                aviso.fecha,
            ],
        )

    def de_destinatario(
        self, rol: Rol, destinatario_id: str | None, solo_no_leidos: bool = False, limite: int = 50
    ) -> list[Aviso]:
        filtro = " AND leido = FALSE" if solo_no_leidos else ""
        filas = self._ejecutar(
            "SELECT datos, leido FROM avisos WHERE rol = ? AND destinatario_id IS NOT DISTINCT FROM ?"
            + filtro
            + " ORDER BY fecha DESC, rowid DESC LIMIT ?",
            [rol.value, destinatario_id, limite],
        )
        return [Aviso.model_validate_json(d).model_copy(update={"leido": bool(leido)}) for d, leido in filas]

    def marcar_leido(self, aviso_id: str, rol: Rol, destinatario_id: str | None) -> bool:
        filas = self._ejecutar(
            "UPDATE avisos SET leido = TRUE WHERE id = ? AND rol = ? "
            "AND destinatario_id IS NOT DISTINCT FROM ? RETURNING id",
            [aviso_id, rol.value, destinatario_id],
        )
        return bool(filas)


class CasosDuckDB(_BaseDuckDB, RepositorioCasos):
    def guardar(self, caso: CasoEscalado) -> None:
        self._ejecutar(
            "INSERT OR REPLACE INTO casos (id, tipo, donativo_id, estado, datos, creado) VALUES (?, ?, ?, ?, ?, ?)",
            [caso.id, caso.tipo.value, caso.donativo_id, caso.estado.value, caso.model_dump_json(), caso.creado],
        )

    def obtener(self, caso_id: str) -> CasoEscalado | None:
        filas = self._ejecutar("SELECT datos FROM casos WHERE id = ?", [caso_id])
        return CasoEscalado.model_validate_json(filas[0][0]) if filas else None

    def abiertos(self) -> list[CasoEscalado]:
        filas = self._ejecutar(
            "SELECT datos FROM casos WHERE estado = ? ORDER BY creado, rowid", [EstadoCaso.ABIERTO.value]
        )
        return [CasoEscalado.model_validate_json(f[0]) for f in filas]

    def abierto_de(self, tipo: TipoCaso, donativo_id: str | None) -> CasoEscalado | None:
        filas = self._ejecutar(
            "SELECT datos FROM casos WHERE tipo = ? AND estado = ? AND donativo_id IS NOT DISTINCT FROM ?",
            [tipo.value, EstadoCaso.ABIERTO.value, donativo_id],
        )
        return CasoEscalado.model_validate_json(filas[0][0]) if filas else None

    def de_donativo(self, donativo_id: str) -> list[CasoEscalado]:
        filas = self._ejecutar(
            "SELECT datos FROM casos WHERE donativo_id = ? ORDER BY creado, rowid", [donativo_id]
        )
        return [CasoEscalado.model_validate_json(f[0]) for f in filas]


class PronosticosDuckDB(_BaseDuckDB, RepositorioPronosticos):
    def guardar(self, pronostico: Pronostico) -> None:
        self._ejecutar(
            "INSERT OR REPLACE INTO pronosticos (id, donante_id, fecha, estado, receptor_sugerido_id, datos) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                pronostico.id,
                pronostico.donante_id,
                pronostico.fecha,
                pronostico.estado.value,
                pronostico.receptor_sugerido_id,
                pronostico.model_dump_json(),
            ],
        )

    def obtener(self, pronostico_id: str) -> Pronostico | None:
        filas = self._ejecutar("SELECT datos FROM pronosticos WHERE id = ?", [pronostico_id])
        return Pronostico.model_validate_json(filas[0][0]) if filas else None

    def _consultar(self, condicion: str, parametros: list) -> list[Pronostico]:
        filas = self._ejecutar(
            f"SELECT datos FROM pronosticos WHERE {condicion} ORDER BY fecha, rowid", parametros
        )
        return [Pronostico.model_validate_json(f[0]) for f in filas]

    def de_donante(self, donante_id: str, desde: date) -> list[Pronostico]:
        return self._consultar("donante_id = ? AND fecha >= ?", [donante_id, desde])

    def de_receptor(self, receptor_id: str, desde: date) -> list[Pronostico]:
        return self._consultar("receptor_sugerido_id = ? AND fecha >= ?", [receptor_id, desde])

    def del_dia(self, fecha: date) -> list[Pronostico]:
        return self._consultar("fecha = ?", [fecha])


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
