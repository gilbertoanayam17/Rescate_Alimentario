"""Prueba de punta a punta del flujo con los agentes de fase 0 y el LLM falso.

Estas pruebas deben SEGUIR pasando cuando cada integrante reemplace su agente: con el LLM
falso sin respuestas programadas, los agentes usan su camino de respaldo determinista.
Por eso usan alimentos de bajo riesgo (pan, jitomate), que son aptos con cualquier regla
razonable, y un caso claramente no apto (queso que huele mal).

Archivo COMPARTIDO (fase 0).
"""
import pytest

from rescate.dominio.enums import EstadoDonativo, TipoEntradaBitacora
from rescate.servicios import ErrorServicio


def test_publicar_asignar_recolectar_entregar(servicio, donante, receptores, recolector):
    r = servicio.publicar("Me sobraron 15 bolillos y 5 kg de jitomate", donante.id)
    assert r.completo
    d = r.donativo
    assert d.estado == EstadoDonativo.ASIGNADO
    assert d.receptor_id in {x.id for x in receptores}
    assert d.kg_totales > 0

    servicio.aceptar_asignacion(d.id, d.receptor_id)
    assert [x.id for x in servicio.disponibles_para_recolectar()] == [d.id]
    servicio.iniciar_recoleccion(d.id, recolector.id)
    final = servicio.confirmar_entrega(d.id, recolector.id)
    assert final.estado == EstadoDonativo.ENTREGADO

    eventos = [h["evento"] for h in servicio.historial(d.id)]
    assert eventos[0] == "publicar" and eventos[-1] == "entregar"
    agentes = {e.agente for e in servicio.bitacora_de(d.id)}
    assert {"Intérprete", "Inocuidad", "Asignador"} <= agentes


def test_texto_sin_alimentos_pide_aclaracion(servicio, donante, receptores):
    r = servicio.publicar("hola, buenas tardes", donante.id)
    assert not r.completo and r.preguntas
    assert servicio.donativos_de_donante(donante.id) == []


def test_alimento_con_senales_de_deterioro_se_rechaza(servicio, donante, receptores):
    r = servicio.publicar("2 kg de queso que ya huele mal", donante.id)
    assert r.donativo.estado == EstadoDonativo.RECHAZADO
    assert r.donativo.asignacion is None


def test_receptor_rechaza_y_se_reasigna(servicio, donante, receptores):
    d = servicio.publicar("20 bolillos", donante.id).donativo
    primero = d.receptor_id
    d = servicio.rechazar_asignacion(d.id, primero, "No tenemos espacio hoy")
    assert d.estado == EstadoDonativo.ASIGNADO
    assert d.receptor_id != primero and primero in d.receptores_descartados


def test_sin_receptor_compatible_queda_evaluado_para_el_coordinador(servicio, donante):
    r = servicio.publicar("10 bolillos", donante.id)  # no hay receptores registrados
    assert r.donativo.estado == EstadoDonativo.EVALUADO
    assert r.donativo.asignacion.requiere_coordinador


def test_no_se_puede_entregar_sin_aceptacion(servicio, donante, receptores, recolector):
    d = servicio.publicar("10 bolillos", donante.id).donativo
    with pytest.raises(ErrorServicio):
        servicio.iniciar_recoleccion(d.id, recolector.id)


def test_la_bitacora_registra_resultados(servicio, donante, receptores):
    d = servicio.publicar("10 bolillos", donante.id).donativo
    tipos = {e.tipo for e in servicio.bitacora_de(d.id)}
    assert TipoEntradaBitacora.RESULTADO in tipos
