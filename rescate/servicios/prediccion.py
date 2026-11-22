"""Pronósticos de excedentes (CAR-07): genera, pre-reserva receptor y avisa. Dueño: Gilberto.

Los pronósticos de un donante se generan una sola vez por día: la primera vez que se piden (al
abrir su página) o cuando el coordinador los genera para todos. La pre-reserva es informativa:
al publicar, el Asignador decide con los datos reales.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, time, timedelta

from rescate.agentes.predictor import AgentePredictor, SolicitudPronostico
from rescate.dominio.enums import EstadoPronostico, Rol, TipoAlimento
from rescate.dominio.modelos import (
    Actor,
    Alimento,
    Aviso,
    Donante,
    Donativo,
    Pronostico,
    Receptor,
    ahora,
)
from rescate.herramientas.compatibilidad import NOMBRE_TIPO, evaluar_compatibilidad
from rescate.herramientas.patrones import detectar_patrones
from rescate.herramientas.puntuacion import construir_contexto, crear_puntuador
from rescate.persistencia.repositorios import (
    RepositorioDonativos,
    RepositorioParticipantes,
    RepositorioPronosticos,
)

from .autorizacion import exigir_rol, participante_del_actor
from .errores import ErrorAutorizacion, ErrorServicio
from .notificaciones import CanalAvisos

#: Sin dictamen todavía, estos tipos se pre-reservan solo con receptores que tienen refrigeración.
REQUIEREN_FRIO = {TipoAlimento.LACTEO, TipoAlimento.CARNE_PESCADO}


class ServicioPrediccion:
    def __init__(
        self,
        agente: AgentePredictor,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
        pronosticos: RepositorioPronosticos,
        canal: CanalAvisos,
        reloj: Callable[[], datetime] = ahora,
    ) -> None:
        self._agente = agente
        self._participantes = participantes
        self._donativos = donativos
        self._pronosticos = pronosticos
        self._canal = canal
        self._reloj = reloj
        self._puntuador = crear_puntuador()
        self._generados: set[tuple[str, date]] = set()

    # ---------------------------------------------------------------- consultas

    def pronosticos_para_donante(self, actor: Actor | None, fecha: date | None = None) -> list[Pronostico]:
        """Los pronósticos vigentes del donante para el día (los genera si aún no existen)."""
        donante = participante_del_actor(actor, Rol.DONANTE, self._participantes)
        fecha = fecha or self._reloj().date()
        self._asegurar(donante, fecha)
        return [
            p
            for p in self._pronosticos.de_donante(donante.id, fecha)
            if p.fecha == fecha and p.estado == EstadoPronostico.VIGENTE
        ]

    def pronosticos_para_receptor(self, actor: Actor | None, desde: date | None = None) -> list[Pronostico]:
        """Los pronósticos vigentes en los que este receptor quedó pre-reservado."""
        receptor = participante_del_actor(actor, Rol.RECEPTOR, self._participantes)
        desde = desde or self._reloj().date()
        return [p for p in self._pronosticos.de_receptor(receptor.id, desde) if p.estado == EstadoPronostico.VIGENTE]

    def generar(self, actor: Actor | None, fecha: date | None = None) -> list[Pronostico]:
        """Coordinador: genera (si faltan) los pronósticos de todos los donantes para el día."""
        exigir_rol(actor, Rol.COORDINADOR)
        fecha = fecha or self._reloj().date()
        for donante in self._participantes.donantes():
            self._asegurar(donante, fecha)
        return self._pronosticos.del_dia(fecha)

    def marcar(self, actor: Actor | None, pronostico_id: str, estado: EstadoPronostico) -> Pronostico:
        """El donante dueño lo marca como publicado ("Publicar ahora") o descartado ("Hoy no")."""
        donante = participante_del_actor(actor, Rol.DONANTE, self._participantes)
        pronostico = self._pronosticos.obtener(pronostico_id)
        if pronostico is None:
            raise ErrorServicio(f"No existe el pronóstico {pronostico_id}.")
        if pronostico.donante_id != donante.id:
            raise ErrorAutorizacion("Ese pronóstico es de otro comercio.")
        if estado == EstadoPronostico.VIGENTE:
            raise ErrorServicio("Un pronóstico solo se marca como publicado o descartado.")
        actualizado = pronostico.model_copy(update={"estado": estado})
        self._pronosticos.guardar(actualizado)
        return actualizado

    # ----------------------------------------------------------------- internos

    def _asegurar(self, donante: Donante, fecha: date) -> None:
        """Genera una sola vez por donante y día (también tras reiniciar: revisa la base)."""
        clave = (donante.id, fecha)
        if clave in self._generados:
            return
        self._generados.add(clave)
        if any(p.fecha == fecha for p in self._pronosticos.de_donante(donante.id, fecha)):
            return
        patrones = detectar_patrones(self._donativos.de_donante(donante.id), fecha)
        if not patrones:
            return
        solicitud = SolicitudPronostico(
            donante=donante, fecha=fecha, patrones=[{**asdict(p), "tipo": p.tipo.value} for p in patrones]
        )
        for pronostico in self._agente.ejecutar(solicitud):
            pronostico.receptor_sugerido_id = self._pre_reservar(donante, pronostico)
            self._pronosticos.guardar(pronostico)
            self._avisar(donante, pronostico)

    def _pre_reservar(self, donante: Donante, pronostico: Pronostico) -> str | None:
        """El mejor receptor para un donativo hipotético del tipo y los kilos esperados, con las
        mismas herramientas deterministas del Asignador (compatibilidad y puntuación)."""
        hipotetico = Donativo(
            donante_id=donante.id,
            texto_original=pronostico.descripcion,
            alimentos=[
                Alimento(
                    nombre=pronostico.descripcion,
                    cantidad=pronostico.kg_esperados,
                    unidad="kg",
                    tipo=pronostico.tipo,
                    kg_estimados=pronostico.kg_esperados,
                )
            ],
        )
        compatibles = [
            r
            for r in self._participantes.receptores()
            if evaluar_compatibilidad(hipotetico, r).compatible
            and (pronostico.tipo not in REQUIEREN_FRIO or r.tiene_refrigeracion)
        ]
        if not compatibles:
            return None
        momento = self._momento_de_excedente(donante, pronostico.fecha)
        candidatos = self._puntuador.clasificar(
            [construir_contexto(hipotetico, donante, r, self._donativos, momento) for r in compatibles]
        )
        return candidatos[0].receptor_id if candidatos else None

    def _momento_de_excedente(self, donante: Donante, fecha: date) -> datetime:
        """Una hora antes del cierre del donante: cuando suele saberse qué sobró."""
        try:
            cierre = time.fromisoformat(donante.hora_cierre)
        except ValueError:
            cierre = time(18, 0)
        return datetime.combine(fecha, cierre) - timedelta(hours=1)

    def _avisar(self, donante: Donante, pronostico: Pronostico) -> None:
        self._canal.enviar(
            Aviso(rol=Rol.DONANTE, destinatario_id=donante.id, titulo="Pronóstico", mensaje=pronostico.mensaje)
        )
        receptor = (
            self._participantes.obtener(pronostico.receptor_sugerido_id) if pronostico.receptor_sugerido_id else None
        )
        if isinstance(receptor, Receptor):
            tipo = NOMBRE_TIPO.get(pronostico.tipo, pronostico.tipo.value)
            self._canal.enviar(
                Aviso(
                    rol=Rol.RECEPTOR,
                    destinatario_id=receptor.id,
                    titulo="Posible donativo hoy",
                    mensaje=f"Posible donativo hoy: unos {pronostico.kg_esperados:g} kg de {tipo} "
                    f"({pronostico.descripcion}) de {donante.nombre}.",
                )
            )
