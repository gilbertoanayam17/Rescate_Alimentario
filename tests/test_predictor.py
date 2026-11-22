"""Agente Predictor y pronósticos (CAR-07): patrones, decisión del LLM validada y servicio."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from rescate.agentes.predictor import (
    AgentePredictor,
    SolicitudPronostico,
    cifras_validas,
    mensaje_de_plantilla,
)
from rescate.bitacora import Bitacora
from rescate.dominio.enums import EstadoDonativo, EstadoPronostico, Rol, TipoAlimento
from rescate.dominio.modelos import (
    Actor,
    Alimento,
    Donante,
    Donativo,
    Receptor,
    Ubicacion,
)
from rescate.herramientas.patrones import detectar_patrones
from rescate.persistencia.db import conectar
from rescate.persistencia.repositorios import BitacoraDuckDB
from rescate.servicios import ErrorAutorizacion, ErrorServicio

LUNES = date(2026, 11, 23)


def donativo(donante_id, dias_antes, nombre="guisado de pollo", kg=3.0, tipo=TipoAlimento.PREPARADO,
             estado=EstadoDonativo.ENTREGADO, fecha=LUNES):
    return Donativo(
        donante_id=donante_id,
        texto_original=f"{kg} kg de {nombre}",
        alimentos=[Alimento(nombre=nombre, cantidad=kg, unidad="kg", tipo=tipo, kg_estimados=kg)],
        estado=estado,
        creado=datetime.combine(fecha - timedelta(days=dias_antes), datetime.min.time()).replace(hour=17),
    )


def lunes_previos(donante_id, semanas, **kwargs):
    """Un donativo en cada uno de los lunes indicados (1 = el lunes pasado)."""
    return [donativo(donante_id, 7 * s, **kwargs) for s in semanas]


# --------------------------------------------------------------------- patrones


def test_seis_de_ocho_lunes_da_confianza_075():
    donativos = lunes_previos("don-1", [1, 2, 3, 5, 6, 8], kg=3.0)
    donativos[0] = donativo("don-1", 7, nombre="tinga", kg=4.0)
    [patron] = detectar_patrones(donativos, LUNES)
    assert (patron.semanas_con_donativo, patron.semanas_observadas, patron.confianza) == (6, 8, 0.75)
    assert patron.dia_semana == 0 and patron.tipo == TipoAlimento.PREPARADO
    assert patron.kg_promedio == round((4 + 3 * 5) / 6, 1)
    assert patron.descripcion == "guisado de pollo y tinga"


def test_comercio_nuevo_con_tres_lunes_seguidos_tiene_confianza_completa():
    [patron] = detectar_patrones(lunes_previos("don-1", [1, 2, 3]), LUNES)
    assert (patron.semanas_con_donativo, patron.semanas_observadas, patron.confianza) == (3, 3, 1.0)


def test_comercio_antiguo_con_tres_de_ocho_lunes_tiene_confianza_baja():
    donativos = [*lunes_previos("don-1", [1, 2, 3]), donativo("don-1", 7 * 12 + 2)]  # dona desde hace meses
    [patron] = detectar_patrones(donativos, LUNES)
    assert (patron.semanas_observadas, patron.confianza) == (8, 0.38)


def test_menos_del_minimo_no_es_patron():
    assert detectar_patrones(lunes_previos("don-1", [1, 2]), LUNES) == []


def test_otro_dia_de_la_semana_no_cuenta():
    martes = [donativo("don-1", 7 * s - 1) for s in (1, 2, 3, 4)]  # los martes no son lunes
    assert detectar_patrones(martes, LUNES) == []


def test_rechazados_cancelados_y_fuera_de_ventana_no_cuentan():
    donativos = [
        *lunes_previos("don-1", [1, 2], estado=EstadoDonativo.RECHAZADO),
        donativo("don-1", 21, estado=EstadoDonativo.CANCELADO),
        donativo("don-1", 0),  # hoy mismo: aún no es historia
        *lunes_previos("don-1", [9, 10, 11]),  # más de 8 semanas atrás
    ]
    assert detectar_patrones(donativos, LUNES) == []


def test_un_patron_por_tipo_y_ordenados_por_confianza():
    donativos = [
        *lunes_previos("don-1", [1, 2, 3]),
        *lunes_previos("don-1", [1, 2, 3, 4, 5], nombre="bolillo", kg=1.4, tipo=TipoAlimento.PANADERIA),
    ]
    tipos = [p.tipo for p in detectar_patrones(donativos, LUNES)]
    assert tipos == [TipoAlimento.PANADERIA, TipoAlimento.PREPARADO]


# ----------------------------------------------------------------------- agente

PATRON = {
    "donante_id": "don-lupe",
    "dia_semana": 0,
    "tipo": "preparado",
    "descripcion": "guisados",
    "semanas_con_donativo": 6,
    "semanas_observadas": 8,
    "kg_promedio": 3.2,
    "confianza": 0.75,
}
LUPE = Donante(id="don-lupe", nombre="Fonda Doña Lupe", ubicacion=Ubicacion(lat=20.67, lon=-103.34))


@pytest.fixture
def bitacora():
    return Bitacora(BitacoraDuckDB(conectar(":memory:")))


@pytest.fixture
def predictor(llm_falso, bitacora):
    return AgentePredictor(llm_falso, bitacora)


def decision(avisar=True, mensaje="Los lunes te suelen sobrar unos 3.2 kg de guisados. ¿Los publicas hoy?"):
    return {"razonamiento": "Es un patrón frecuente.", "avisar": avisar, "mensaje": mensaje}


def pedir(predictor, *patrones):
    return predictor.ejecutar(SolicitudPronostico(donante=LUPE, fecha=LUNES, patrones=list(patrones)))


def test_el_llm_decide_avisar_y_redacta(predictor, llm_falso):
    llm_falso.programar("DecisionPronostico", decision())
    [p] = pedir(predictor, PATRON)
    assert p.mensaje.startswith("Los lunes te suelen sobrar")
    assert (p.kg_esperados, p.confianza, p.tipo) == (3.2, 0.75, TipoAlimento.PREPARADO)  # del código
    _, prompt = llm_falso.llamadas[-1]
    assert prompt.startswith("<datos_patron>") and "kg_promedio (calculado por el sistema): 3.2" in prompt


def test_el_llm_puede_decidir_no_avisar(predictor, llm_falso):
    llm_falso.programar("DecisionPronostico", decision(avisar=False))
    assert pedir(predictor, PATRON) == []


def test_sin_llm_usa_la_plantilla(predictor, bitacora):
    [p] = pedir(predictor, PATRON)
    assert p.mensaje == "Los lunes sueles donar guisados (unos 3.2 kg). ¿Quieres publicarlo hoy?"
    assert any(e.tipo.value == "error" for e in bitacora.recientes())


@pytest.mark.parametrize(
    "mensaje",
    ["Hoy te sobrarán unos 10 kg de guisados.", "", "x" * 301],
)
def test_mensaje_invalido_usa_la_plantilla(predictor, llm_falso, mensaje):
    llm_falso.programar("DecisionPronostico", decision(mensaje=mensaje))
    [p] = pedir(predictor, PATRON)
    assert p.mensaje == mensaje_de_plantilla(PATRON)


def test_confianza_baja_no_llega_al_llm(predictor, llm_falso):
    assert pedir(predictor, {**PATRON, "confianza": 0.38, "semanas_con_donativo": 3}) == []
    assert llm_falso.llamadas == []


def test_cifras_validas():
    assert cifras_validas("unos 3.2 kg de guisados", 3.2)
    assert cifras_validas("unos 3 kilos", 3.2)  # redondeo aceptado
    assert cifras_validas("30 piezas de pan", 2.1)  # no son kilos
    assert not cifras_validas("unos 5 kg", 3.2)
    assert not cifras_validas("3,9 kilos", 3.2)


# ---------------------------------------------------------------------- servicio


@pytest.fixture
def lupe(servicios, coordinador, repos):
    servicios.participantes.registrar(coordinador, LUPE)
    for d in lunes_previos(LUPE.id, [1, 2, 3, 4, 6, 8], kg=3.0):
        repos.donativos.guardar(d)
    return LUPE


@pytest.fixture
def receptores_g3(servicios, coordinador):
    lista = [
        Receptor(id="rec-sin-frio", nombre="Comedor Sin Frío", ubicacion=Ubicacion(lat=20.6705, lon=-103.3405),
                 tiene_refrigeracion=False),
        Receptor(id="rec-con-frio", nombre="Albergue Con Frío", ubicacion=Ubicacion(lat=20.6157, lon=-103.3468),
                 tiene_refrigeracion=True),
    ]
    for r in lista:
        servicios.participantes.registrar(coordinador, r)
    return lista


def actor(p):
    return Actor(rol=p.rol, participante_id=p.id)


def test_genera_una_sola_vez_por_dia(servicios, llm_falso, repos, lupe, receptores_g3):
    primeros = servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    segundos = servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    assert len(primeros) == 1 and [p.id for p in segundos] == [primeros[0].id]
    assert len(repos.pronosticos.del_dia(LUNES)) == 1
    p = primeros[0]
    assert p.confianza == 0.75 and p.kg_esperados == 3.0
    assert p.receptor_sugerido_id == "rec-sin-frio"  # el más cercano; un guisado no exige frío


def test_tras_reiniciar_no_se_duplica(aplicacion, servicios, repos, lupe, receptores_g3):
    from rescate.servicios.prediccion import ServicioPrediccion

    servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    nuevo = ServicioPrediccion(
        AgentePredictor(aplicacion.llm, aplicacion.bitacora),
        repos.participantes, repos.donativos, repos.pronosticos, servicios.prediccion._canal,
    )
    assert len(nuevo.pronosticos_para_donante(actor(lupe), LUNES)) == 1
    assert len(repos.pronosticos.del_dia(LUNES)) == 1


def test_la_pre_reserva_de_lacteos_exige_refrigeracion(servicios, coordinador, repos, receptores_g3):
    queseria = Donante(id="don-queso", nombre="Cremería", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    servicios.participantes.registrar(coordinador, queseria)
    for d in lunes_previos(queseria.id, [1, 2, 3, 4], nombre="queso fresco", kg=2.0, tipo=TipoAlimento.LACTEO):
        repos.donativos.guardar(d)
    [p] = servicios.prediccion.pronosticos_para_donante(actor(queseria), LUNES)
    assert p.receptor_sugerido_id == "rec-con-frio"  # aunque el otro está más cerca


def test_los_avisos_se_guardan_una_vez(servicios, lupe, receptores_g3):
    servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    al_donante = servicios.notificaciones.avisos(actor(lupe))
    al_receptor = servicios.notificaciones.avisos(actor(receptores_g3[0]))
    assert [a.titulo for a in al_donante] == ["Pronóstico"]
    assert len(al_receptor) == 1 and al_receptor[0].mensaje.startswith("Posible donativo hoy: unos 3 kg")
    assert "Fonda Doña Lupe" in al_receptor[0].mensaje
    assert servicios.notificaciones.avisos(actor(receptores_g3[1])) == []


def test_cada_quien_ve_solo_lo_suyo(servicios, coordinador, lupe, receptores_g3, donante):
    [p] = servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    assert servicios.prediccion.pronosticos_para_donante(actor(donante), LUNES) == []  # sin historial
    with pytest.raises(ErrorAutorizacion):
        servicios.prediccion.marcar(actor(donante), p.id, EstadoPronostico.DESCARTADO)
    assert [x.id for x in servicios.prediccion.pronosticos_para_receptor(actor(receptores_g3[0]), LUNES)] == [p.id]
    assert servicios.prediccion.pronosticos_para_receptor(actor(receptores_g3[1]), LUNES) == []
    with pytest.raises(ErrorAutorizacion):
        servicios.prediccion.pronosticos_para_receptor(actor(lupe), LUNES)
    with pytest.raises(ErrorAutorizacion):
        servicios.prediccion.generar(actor(lupe), LUNES)


def test_marcar_lo_saca_de_los_vigentes(servicios, lupe, receptores_g3):
    [p] = servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES)
    marcado = servicios.prediccion.marcar(actor(lupe), p.id, EstadoPronostico.PUBLICADO)
    assert marcado.estado == EstadoPronostico.PUBLICADO
    assert servicios.prediccion.pronosticos_para_donante(actor(lupe), LUNES) == []
    assert servicios.prediccion.pronosticos_para_receptor(actor(receptores_g3[0]), LUNES) == []
    with pytest.raises(ErrorServicio):
        servicios.prediccion.marcar(actor(lupe), p.id, EstadoPronostico.VIGENTE)


def test_el_coordinador_genera_para_todos(servicios, coordinador, lupe, receptores_g3, donante):
    generados = servicios.prediccion.generar(coordinador, LUNES)
    assert [p.donante_id for p in generados] == [lupe.id]


def test_otro_dia_sin_patron_no_genera(servicios, lupe, receptores_g3):
    martes = LUNES + timedelta(days=1)
    assert servicios.prediccion.pronosticos_para_donante(actor(lupe), martes) == []


def test_rol_en_la_barra_lateral_no_basta(servicios, lupe, receptores_g3):
    impostor = Actor(rol=Rol.DONANTE, participante_id=receptores_g3[0].id)
    with pytest.raises(ErrorAutorizacion):
        servicios.prediccion.pronosticos_para_donante(impostor, LUNES)
