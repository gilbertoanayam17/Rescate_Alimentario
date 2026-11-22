"""Prueba de punta a punta del flujo con el LLM falso.

Estas pruebas deben SEGUIR pasando cuando cada integrante cambie su agente: con el LLM
falso sin respuestas programadas, los agentes usan su camino de respaldo determinista.
Por eso usan alimentos de bajo riesgo (pan, jitomate), que son aptos con cualquier regla
razonable, y un caso claramente no apto (queso que huele mal).

Archivo COMPARTIDO.
"""
import pytest

from rescate.dominio.enums import EstadoDonativo, TipoCaso, TipoEntradaBitacora
from rescate.servicios import ErrorServicio


def test_publicar_asignar_recolectar_entregar(servicios, actor_de, coordinador, donante, receptores, recolector):
    r = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 15 bolillos y 5 kg de jitomate")
    assert r.completo
    d = r.donativo
    assert d.estado == EstadoDonativo.ASIGNADO
    assert d.receptor_id in {x.id for x in receptores}
    assert d.kg_totales > 0

    receptor = next(x for x in receptores if x.id == d.receptor_id)
    servicios.distribucion.aceptar(actor_de(receptor), d.id)
    voluntario = actor_de(recolector)
    assert [x.id for x in servicios.distribucion.disponibles_para_recolectar(voluntario)] == [d.id]
    servicios.distribucion.iniciar_recoleccion(voluntario, d.id)
    final = servicios.distribucion.confirmar_entrega(voluntario, d.id)
    assert final.estado == EstadoDonativo.ENTREGADO

    eventos = [h["evento"] for h in servicios.reportes.historial(coordinador, d.id)]
    assert eventos[0] == "publicar" and eventos[-1] == "entregar"
    agentes = {e.agente for e in servicios.reportes.bitacora_de(coordinador, d.id)}
    assert {"Intérprete", "Inocuidad", "Asignador"} <= agentes


def test_texto_sin_alimentos_pide_aclaracion(servicios, actor_de, donante, receptores):
    r = servicios.publicacion.publicar(actor_de(donante), "hola, buenas tardes")
    assert not r.completo and r.preguntas
    assert servicios.publicacion.donativos_de_donante(actor_de(donante)) == []


def test_alimento_con_senales_de_deterioro_se_rechaza(servicios, actor_de, donante, receptores):
    r = servicios.publicacion.publicar(actor_de(donante), "2 kg de queso que ya huele mal")
    assert r.donativo.estado == EstadoDonativo.RECHAZADO
    assert r.donativo.asignacion is None


def test_receptor_rechaza_y_se_reasigna(servicios, actor_de, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    primero = next(x for x in receptores if x.id == d.receptor_id)
    d = servicios.distribucion.rechazar(actor_de(primero), d.id, "No tenemos espacio hoy")
    assert d.estado == EstadoDonativo.ASIGNADO
    assert d.receptor_id != primero.id and primero.id in d.receptores_descartados


def test_sin_receptor_compatible_queda_evaluado_para_el_coordinador(servicios, actor_de, coordinador, donante):
    r = servicios.publicacion.publicar(actor_de(donante), "10 bolillos")  # no hay receptores registrados
    assert r.donativo.estado == EstadoDonativo.EVALUADO
    assert r.donativo.asignacion.requiere_coordinador
    casos = servicios.casos.abiertos(coordinador)
    assert [(c.tipo, c.donativo_id) for c in casos] == [(TipoCaso.SIN_RECEPTOR, r.donativo.id)]


def test_no_se_puede_entregar_sin_aceptacion(servicios, actor_de, donante, receptores, recolector):
    d = servicios.publicacion.publicar(actor_de(donante), "10 bolillos").donativo
    with pytest.raises(ErrorServicio):
        servicios.distribucion.iniciar_recoleccion(actor_de(recolector), d.id)


def test_la_bitacora_registra_resultados(servicios, actor_de, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "10 bolillos").donativo
    tipos = {e.tipo for e in servicios.reportes.bitacora_de(actor_de(donante), d.id)}
    assert TipoEntradaBitacora.RESULTADO in tipos
