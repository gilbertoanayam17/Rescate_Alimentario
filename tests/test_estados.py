"""Pruebas del ciclo de vida del donativo (CAR-05). Archivo COMPARTIDO (fase 0)."""
import pytest

from rescate.dominio.enums import EstadoDonativo, Evento
from rescate.dominio.estados import ESTADOS, TransicionInvalida, aplicar_evento
from rescate.dominio.modelos import Alimento, Donativo


def nuevo_donativo() -> Donativo:
    return Donativo(donante_id="d1", texto_original="10 bolillos", alimentos=[Alimento(nombre="bolillos", cantidad=10)])


def test_camino_feliz_hasta_entregado():
    d = nuevo_donativo()
    for evento in [Evento.EVALUAR_APTO, Evento.ASIGNAR, Evento.INICIAR_RECOLECCION, Evento.ENTREGAR]:
        aplicar_evento(d, evento)
    assert d.estado == EstadoDonativo.ENTREGADO
    assert ESTADOS[d.estado].es_final


def test_no_apto_termina_en_rechazado():
    d = nuevo_donativo()
    assert aplicar_evento(d, Evento.EVALUAR_NO_APTO) == (EstadoDonativo.PUBLICADO, EstadoDonativo.RECHAZADO)
    with pytest.raises(TransicionInvalida):
        aplicar_evento(d, Evento.ASIGNAR)


def test_receptor_rechaza_y_vuelve_a_evaluado():
    d = nuevo_donativo()
    aplicar_evento(d, Evento.EVALUAR_APTO)
    aplicar_evento(d, Evento.ASIGNAR)
    aplicar_evento(d, Evento.LIBERAR)
    assert d.estado == EstadoDonativo.EVALUADO


@pytest.mark.parametrize("evento", [Evento.ASIGNAR, Evento.ENTREGAR, Evento.INICIAR_RECOLECCION, Evento.LIBERAR])
def test_eventos_invalidos_desde_publicado(evento):
    with pytest.raises(TransicionInvalida):
        aplicar_evento(nuevo_donativo(), evento)


def test_todos_los_estados_tienen_clase():
    assert set(ESTADOS) == set(EstadoDonativo)
