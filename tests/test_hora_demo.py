"""Hora de demo (HORA_DEMO): todo el reloj de la app corre desde esa hora sin tocar el de la PC."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rescate.config import cargar_configuracion
from rescate.dominio.modelos import ahora, fijar_hora_demo


def cerca(a: datetime, b: datetime, segundos: int = 5) -> bool:
    return abs((a - b).total_seconds()) <= segundos


def test_ahora_corre_desde_la_hora_de_demo():
    fijar_hora_demo("16:00")
    esperado = datetime.combine(datetime.now().date(), datetime.min.time()).replace(hour=16)
    assert cerca(ahora(), esperado)


def test_sin_hora_de_demo_es_la_hora_real():
    fijar_hora_demo("16:00")
    fijar_hora_demo(None)
    assert cerca(ahora(), datetime.now())
    fijar_hora_demo("")
    assert cerca(ahora(), datetime.now())


def test_repetir_la_misma_hora_no_reinicia_el_reloj(monkeypatch):
    from rescate.dominio import modelos

    fijar_hora_demo("16:00")
    desfase = modelos._desfase
    real = datetime.now()
    monkeypatch.setattr(modelos, "datetime", type("Reloj", (datetime,), {"now": staticmethod(lambda: real + timedelta(minutes=30))}))
    fijar_hora_demo("16:00")  # Streamlit vuelve a leer la configuración: el reloj sigue avanzando
    assert modelos._desfase == desfase


def test_la_configuracion_aplica_hora_demo_del_env(monkeypatch):
    monkeypatch.setenv("HORA_DEMO", "13:30")
    config = cargar_configuracion()
    assert config.hora_demo == "13:30"
    assert ahora().strftime("%H:%M") in {"13:30", "13:31"}


def test_hora_demo_invalida_da_un_error_claro(monkeypatch):
    monkeypatch.setenv("HORA_DEMO", "4 de la tarde")
    with pytest.raises(ValueError, match="HH:MM"):
        cargar_configuracion()


def test_historial_bitacora_y_constancia_usan_la_hora_de_demo(servicios, actor_de, coordinador, donante, receptores, recolector):
    fijar_hora_demo("16:00")
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    receptor = next(r for r in receptores if r.id == d.receptor_id)
    servicios.distribucion.aceptar(actor_de(receptor), d.id)
    servicios.distribucion.iniciar_recoleccion(actor_de(recolector), d.id)
    servicios.distribucion.confirmar_entrega(actor_de(recolector), d.id)

    a_las_16 = datetime.combine(datetime.now().date(), datetime.min.time()).replace(hour=16)
    final = servicios.reportes.donativo(coordinador, d.id)
    assert cerca(final.creado, a_las_16, 60) and cerca(final.actualizado, a_las_16, 60)
    assert all(cerca(h["fecha"], a_las_16, 60) for h in servicios.reportes.historial(coordinador, d.id))
    assert all(cerca(e.fecha, a_las_16, 60) for e in servicios.reportes.bitacora_de(coordinador, d.id))
    pdf = servicios.reportes.constancia_pdf(coordinador, d.id, comprimir=False)
    assert a_las_16.strftime("%d/%m/%Y 16:0").encode() in pdf
