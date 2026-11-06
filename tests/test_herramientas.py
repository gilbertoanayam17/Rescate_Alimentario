"""Cálculos y límites de horario con datos fijos."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from rescate.dominio.modelos import (
    Alimento,
    Asignacion,
    DictamenInocuidad,
    Donativo,
    Receptor,
    Ubicacion,
    ahora,
)
from rescate.herramientas.capacidad import kg_disponibles
from rescate.herramientas.compatibilidad import evaluar_compatibilidad
from rescate.herramientas.equidad import kg_recibidos_semana
from rescate.herramientas.horario import limite_recoleccion, puede_recibir_a_tiempo
from rescate.herramientas.puntuacion import (
    ContextoPuntuacion,
    CriterioPuntuacion,
    Puntuador,
    crear_puntuador,
)


@pytest.fixture
def datos(donante):
    t = datetime(2026, 11, 5, 12)
    d = Donativo(
        donante_id=donante.id,
        texto_original="pan",
        alimentos=[
            Alimento(nombre="pan", cantidad=10, kg_estimados=10, tipo="panaderia")
        ],
        creado=t,
        recoger_antes_de=t + timedelta(hours=4),
    )
    r = Receptor(nombre="Comedor", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    return t, d, r


def test_ventana_y_caducidad(datos):
    t, d, r = datos
    assert puede_recibir_a_tiempo(r, d, t)[0]
    r.hora_cierre = "11:00"
    assert not puede_recibir_a_tiempo(r, d, t)[0]
    d.dictamen = DictamenInocuidad(dictamen="apto", motivo="Prueba", vida_util_horas=1)
    assert limite_recoleccion(d, t) == t + timedelta(hours=1)
    assert not puede_recibir_a_tiempo(r, d, t + timedelta(hours=2))[0]


def test_turno_nocturno(datos):
    t, d, r = datos
    t = t.replace(hour=23)
    d.recoger_antes_de = t + timedelta(hours=3)
    r.hora_apertura, r.hora_cierre = "22:00", "02:00"
    assert puede_recibir_a_tiempo(r, d, t)[0]


def test_tipo_no_aceptado(datos):
    _, d, r = datos
    r.tipos_aceptados = []
    assert not evaluar_compatibilidad(d, r).compatible


def test_capacidad_y_equidad(datos, servicio):
    _, d, r = datos
    from rescate.dominio.enums import EstadoDonativo

    d.estado = EstadoDonativo.ENTREGADO
    d.asignacion = Asignacion(receptor_id=r.id)
    d.actualizado = ahora() - timedelta(days=3)
    servicio.repo_donativos.guardar(d)
    assert kg_disponibles(r, servicio.repo_donativos) == 40
    assert kg_recibidos_semana(r.id, servicio.repo_donativos) == 10
    d.actualizado = ahora() - timedelta(days=10)
    servicio.repo_donativos.guardar(d)
    assert kg_recibidos_semana(r.id, servicio.repo_donativos) == 0


def test_criterios_extensibles(datos, donante):
    _, d, r = datos
    ctx = ContextoPuntuacion(d, donante, r, 1, 50, True, 0)
    lejos = replace(ctx, receptor=r.model_copy(update={"id": "lejos"}), distancia_km=10)
    puntuador = crear_puntuador()
    assert puntuador.clasificar([lejos, ctx])[0].receptor_id == r.id
    assert (
        puntuador.clasificar([replace(ctx, kg_disponibles=0)])[0].total
        < puntuador.clasificar([ctx])[0].total
    )

    class Constante(CriterioPuntuacion):
        nombre, peso = "nuevo", 1

        def puntuar(self, ctx):
            return 0.8

        def explicar(self, ctx):
            return "Nuevo criterio"

    assert Puntuador([Constante()]).clasificar([ctx])[0].total == 0.8


@pytest.mark.parametrize(
    "cambios",
    [
        dict(distancia_km=10),
        dict(kg_disponibles=0),
        dict(abierto_a_tiempo=False),
        dict(kg_recibidos_semana=90),
    ],
)
def test_cada_estrategia_cambia_el_orden(datos, donante, cambios):
    _, d, r = datos
    mejor = ContextoPuntuacion(d, donante, r, 1, 50, True, 0)
    peor = replace(mejor, receptor=r.model_copy(update={"id": "peor"}), **cambios)
    candidatos = crear_puntuador().clasificar([peor, mejor])
    assert candidatos[0].receptor_id == r.id
    assert 0 <= candidatos[1].total < candidatos[0].total <= 1
    assert all(0 <= valor <= 1 for c in candidatos for valor in c.desglose.values())


def test_puntaje_suma_ponderada_y_desempate_estable(datos, donante):
    _, d, r = datos
    ctx = ContextoPuntuacion(d, donante, r, 3, 5, True, 20)
    otro = replace(ctx, receptor=r.model_copy(update={"id": "aaa"}))
    candidato = crear_puntuador().clasificar([ctx])[0]
    assert candidato.total == round(0.35 * 0.8 + 0.25 * 0.5 + 0.25 + 0.15 * 0.8, 3)
    clasificados = crear_puntuador().clasificar([ctx, otro])
    assert [c.receptor_id for c in clasificados] == sorted([r.id, "aaa"])


def test_capacidad_solo_cuenta_compromisos_activos_del_dia(datos, servicio):
    from rescate.dominio.enums import EstadoDonativo as E

    t, d, r = datos
    r.capacidad_kg_dia = 25
    for i, estado in enumerate(
        [
            E.ASIGNADO,
            E.EN_RECOLECCION,
            E.ENTREGADO,
            E.CANCELADO,
            E.EXPIRADO,
            E.RECHAZADO,
        ]
    ):
        copia = d.model_copy(deep=True)
        copia.id = f"donativo-{i}"
        copia.estado = estado
        copia.asignacion = Asignacion(receptor_id=r.id, fecha=t)
        servicio.repo_donativos.guardar(copia)
    assert kg_disponibles(r, servicio.repo_donativos, t.date()) == 0
    assert (
        kg_disponibles(r, servicio.repo_donativos, (t + timedelta(days=1)).date()) == 25
    )


def test_filtros_duros_explican_todos_los_motivos(datos):
    _, d, r = datos
    d.receptores_descartados = [r.id]
    r.tipos_aceptados = []
    d.dictamen = DictamenInocuidad(
        dictamen="no_apto", motivo="Deterioro", requiere_refrigeracion=True
    )
    resultado = evaluar_compatibilidad(d, r)
    assert not resultado.compatible
    assert len(resultado.motivos) == 4


def test_horario_limites_y_turno_iniciado_ayer(datos):
    t, d, r = datos
    r.hora_cierre = "12:00"
    assert not puede_recibir_a_tiempo(r, d, t)[0]
    r.hora_apertura, r.hora_cierre = "16:00", "20:00"
    assert not puede_recibir_a_tiempo(r, d, t)[0]
    d.recoger_antes_de = t + timedelta(hours=4, seconds=1)
    assert puede_recibir_a_tiempo(r, d, t)[0]
    madrugada = t.replace(hour=1)
    d.recoger_antes_de = madrugada + timedelta(hours=1)
    r.hora_apertura, r.hora_cierre = "22:00", "02:00"
    assert puede_recibir_a_tiempo(r, d, madrugada)[0]


def test_vida_util_usa_preparacion_y_plazo_mas_estricto(datos):
    t, d, _ = datos
    d.hora_preparacion = t - timedelta(hours=1)
    d.dictamen = DictamenInocuidad(dictamen="apto", motivo="Prueba", vida_util_horas=2)
    assert limite_recoleccion(d, t) == t + timedelta(hours=1)
    d.recoger_antes_de = t + timedelta(minutes=30)
    assert limite_recoleccion(d, t) == t + timedelta(minutes=30)
    d.recoger_antes_de, d.dictamen = None, None
    assert limite_recoleccion(d, t) == t + timedelta(hours=4)
