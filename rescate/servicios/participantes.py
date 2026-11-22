"""Alta, edición, baja y sesión de participantes (CAR-09). Una de las tres partes de SRP."""
from __future__ import annotations

from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor, Participante
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes

from .autorizacion import es_coordinador, exigir_rol
from .errores import ErrorAutorizacion, ErrorServicio


class ServicioParticipantes:
    def __init__(self, participantes: RepositorioParticipantes, donativos: RepositorioDonativos) -> None:
        self._participantes = participantes
        self._donativos = donativos

    # ---------------------------------------------------------------- lectura

    def listar(self, rol: Rol | None = None) -> list[Participante]:
        """Lectura libre: la usa la pantalla de entrada para elegir participante."""
        return self._participantes.listar(rol)

    def obtener(self, participante_id: str | None) -> Participante | None:
        return self._participantes.obtener(participante_id) if participante_id else None

    # --------------------------------------------------------------- escritura

    def registrar(self, actor: Actor | None, participante: Participante) -> Participante:
        """Alta o edición (mismo id = edición). El coordinador puede todo; un participante solo
        edita su propio perfil, sin cambiar de rol ni de PIN."""
        if not participante.nombre.strip():
            raise ErrorServicio("El nombre es obligatorio.")
        if not es_coordinador(actor):
            exigir_rol(actor, Rol.DONANTE, Rol.RECEPTOR, Rol.RECOLECTOR)
            guardado = self._participantes.obtener(participante.id)
            if (
                guardado is None
                or actor.participante_id != participante.id
                or guardado.rol != participante.rol
                or actor.rol != guardado.rol
            ):
                raise ErrorAutorizacion("Solo puedes editar tu propio perfil.")
            participante = participante.model_copy(update={"pin_hash": guardado.pin_hash})
        self._participantes.guardar(participante)
        return participante

    def vinculado(self, participante_id: str) -> bool:
        """True si aparece en algún donativo; se conserva para no romper el historial."""
        return any(
            participante_id in (d.donante_id, d.receptor_id, d.recolector_id)
            or participante_id in d.receptores_descartados
            or (d.asignacion is not None and participante_id in d.asignacion.alternativas)
            for d in self._donativos.listar()
        )

    def eliminar(self, actor: Actor | None, participante_id: str) -> None:
        exigir_rol(actor, Rol.COORDINADOR)
        if self.vinculado(participante_id):
            raise ErrorServicio("Conservamos participantes vinculados a donativos para mantener el historial.")
        self._participantes.eliminar(participante_id)

    # ------------------------------------------------------------------ sesión

    def iniciar_sesion(self, participante_id: str, pin: str = "") -> Actor:
        """Crea el Actor a partir del participante guardado (el PIN lo agrega la tarea A7)."""
        participante = self._participantes.obtener(participante_id)
        if participante is None:
            raise ErrorAutorizacion("No existe ese participante.")
        return Actor(rol=participante.rol, participante_id=participante.id)

    def sesion_coordinador(self, pin: str = "") -> Actor:
        """Sesión del coordinador (el PIN lo agrega la tarea A7)."""
        return Actor(rol=Rol.COORDINADOR)
