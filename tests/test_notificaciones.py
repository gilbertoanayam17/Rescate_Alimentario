"""Notificaciones (CAR-06): Observer del ciclo de vida, canal de avisos y bandeja por actor."""
from __future__ import annotations

import pytest

from rescate.dominio.enums import EstadoDonativo, Rol
from rescate.dominio.modelos import Actor, Aviso, EventoDonativo
from rescate.servicios import ErrorAutorizacion
from rescate.servicios.eventos import ObservadorEventos


def mensajes(servicios, actor) -> list[str]:
    return [a.mensaje for a in servicios.notificaciones.avisos(actor)]


def publicar_asignado(servicios, actor_de, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    assert d.estado == EstadoDonativo.ASIGNADO
    receptor = next(r for r in receptores if r.id == d.receptor_id)
    return d, receptor


def test_asignar_avisa_al_receptor_y_al_donante(servicios, actor_de, donante, receptores):
    d, receptor = publicar_asignado(servicios, actor_de, donante, receptores)
    assert mensajes(servicios, actor_de(receptor)) == [f"Nuevo donativo por confirmar: {d.resumen()}"]
    assert f"Tu donativo se asignó a {receptor.nombre}" in mensajes(servicios, actor_de(donante))
    otro = next(r for r in receptores if r.id != receptor.id)
    assert mensajes(servicios, actor_de(otro)) == []


def test_no_apto_avisa_al_donante_con_el_motivo(servicios, actor_de, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "2 kg de queso que ya huele mal").donativo
    avisos = mensajes(servicios, actor_de(donante))
    assert avisos == [f"Tu donativo no se puede donar: {d.dictamen.motivo}"]


def test_rechazo_avisa_al_donante_y_al_nuevo_receptor(servicios, actor_de, donante, receptores):
    d, primero = publicar_asignado(servicios, actor_de, donante, receptores)
    d = servicios.distribucion.rechazar(actor_de(primero), d.id, "Sin espacio")
    segundo = next(r for r in receptores if r.id == d.receptor_id)
    del_donante = mensajes(servicios, actor_de(donante))
    assert f"{primero.nombre} no pudo recibirlo (Sin espacio); buscamos otro receptor" in del_donante
    assert f"Tu donativo se asignó a {segundo.nombre}" in del_donante
    assert mensajes(servicios, actor_de(segundo)) == [f"Nuevo donativo por confirmar: {d.resumen()}"]


def test_aceptar_recolectar_y_entregar(servicios, actor_de, coordinador, donante, receptores, recolector):
    from rescate.dominio.modelos import Recolector, Ubicacion

    ocupado = Recolector(
        id="vol-ocupado", nombre="Ocupado", ubicacion=Ubicacion(lat=20.67, lon=-103.34), disponible=False
    )
    servicios.participantes.registrar(coordinador, ocupado)
    d, receptor = publicar_asignado(servicios, actor_de, donante, receptores)

    servicios.distribucion.aceptar(actor_de(receptor), d.id)
    assert f"{receptor.nombre} aceptó tu donativo" in mensajes(servicios, actor_de(donante))
    assert mensajes(servicios, actor_de(recolector)) == ["Hay un donativo listo para recoger en Fonda de Prueba"]
    assert mensajes(servicios, actor_de(ocupado)) == []

    servicios.distribucion.iniciar_recoleccion(actor_de(recolector), d.id)
    en_camino = f"{recolector.nombre} va en camino"
    assert en_camino in mensajes(servicios, actor_de(donante))
    assert en_camino in mensajes(servicios, actor_de(receptor))

    servicios.distribucion.confirmar_entrega(actor_de(recolector), d.id)
    entregado = "Entregado. Ya puedes descargar la constancia."
    assert entregado in mensajes(servicios, actor_de(donante))
    assert entregado in mensajes(servicios, actor_de(receptor))
    assert all(a.donativo_id == d.id for a in servicios.notificaciones.avisos(actor_de(receptor)))


def test_cancelar_avisa_a_los_involucrados_menos_a_quien_cancela(servicios, actor_de, donante, receptores):
    d, receptor = publicar_asignado(servicios, actor_de, donante, receptores)
    servicios.publicacion.cancelar(actor_de(donante), d.id)
    assert "El donativo se canceló" in mensajes(servicios, actor_de(receptor))
    assert "El donativo se canceló" not in mensajes(servicios, actor_de(donante))


def test_expirar_avisa_a_los_involucrados(aplicacion, servicios, actor_de, donante, receptores):
    d, receptor = publicar_asignado(servicios, actor_de, donante, receptores)
    d.estado = EstadoDonativo.EXPIRADO
    aplicacion.repos.donativos.guardar(d)
    aplicacion.bus.publicar(
        EventoDonativo(donativo_id=d.id, evento="expirar", anterior=EstadoDonativo.ASIGNADO, nuevo=d.estado)
    )
    assert "El donativo venció sin recogerse" in mensajes(servicios, actor_de(receptor))
    assert "El donativo venció sin recogerse" in mensajes(servicios, actor_de(donante))


def test_eventos_sin_aviso_o_de_donativos_inexistentes(aplicacion, servicios, actor_de, donante):
    aplicacion.bus.publicar(EventoDonativo(donativo_id="no-existe", evento="asignar", nuevo=EstadoDonativo.ASIGNADO))
    assert mensajes(servicios, actor_de(donante)) == []


def test_un_observador_que_falla_no_rompe_la_transicion(aplicacion, servicios, actor_de, donante, receptores):
    class Roto(ObservadorEventos):
        def al_ocurrir(self, evento):
            raise RuntimeError("falla a propósito")

    aplicacion.bus.suscribir(Roto())
    d, receptor = publicar_asignado(servicios, actor_de, donante, receptores)
    assert servicios.distribucion.aceptar(actor_de(receptor), d.id).asignacion.aceptada
    assert f"{receptor.nombre} aceptó tu donativo" in mensajes(servicios, actor_de(donante))


def test_no_leidos_y_marcar_leido(servicios, actor_de, donante, receptores):
    publicar_asignado(servicios, actor_de, donante, receptores)
    actor = actor_de(donante)
    assert servicios.notificaciones.no_leidos(actor) == 1
    aviso = servicios.notificaciones.avisos(actor)[0]
    servicios.notificaciones.marcar_leido(actor, aviso.id)
    assert servicios.notificaciones.no_leidos(actor) == 0
    assert servicios.notificaciones.avisos(actor)[0].leido
    assert servicios.notificaciones.avisos(actor, solo_no_leidos=True) == []


def test_marcar_leido_solo_funciona_con_avisos_propios(servicios, actor_de, donante, receptores):
    _, receptor = publicar_asignado(servicios, actor_de, donante, receptores)
    ajeno = servicios.notificaciones.avisos(actor_de(donante))[0]
    with pytest.raises(ErrorAutorizacion):
        servicios.notificaciones.marcar_leido(actor_de(receptor), ajeno.id)
    assert servicios.notificaciones.no_leidos(actor_de(donante)) == 1


def test_el_coordinador_ve_los_avisos_de_la_coordinacion(aplicacion, servicios, coordinador, donante):
    aplicacion.repos.avisos.agregar(Aviso(rol=Rol.COORDINADOR, titulo="Caso", mensaje="Hay un caso nuevo"))
    assert mensajes(servicios, coordinador) == ["Hay un caso nuevo"]
    assert servicios.notificaciones.no_leidos(coordinador) == 1


def test_sin_sesion_o_con_rol_falso_no_hay_avisos(servicios, donante):
    with pytest.raises(ErrorAutorizacion):
        servicios.notificaciones.avisos(None)
    with pytest.raises(ErrorAutorizacion):
        servicios.notificaciones.avisos(Actor(rol=Rol.RECEPTOR, participante_id=donante.id))
