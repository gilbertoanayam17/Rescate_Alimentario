"""Constancia de entrega y reporte ESG en PDF con Template Method (CAR-12)."""
from __future__ import annotations

from datetime import timedelta
from typing import ClassVar

import pytest

from rescate.documentos import LEYENDA_CONSTANCIA, ConstanciaEntrega, GeneradorDocumento
from rescate.documentos.base import a_latin1
from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor, Alimento, Donativo, Receptor, Ubicacion, ahora
from rescate.servicios import ErrorAutorizacion, ErrorServicio

HOY = ahora().date()


def texto_pdf(pdf: bytes) -> str:
    """Contenido de un PDF sin comprimir, sin los escapes de paréntesis de los textos."""
    return pdf.decode("latin-1").replace(r"\(", "(").replace(r"\)", ")")


def entregar(servicios, actor_de, donante, receptores, recolector, texto="Me sobraron 15 bolillos y 5 kg de jitomate"):
    d = servicios.publicacion.publicar(actor_de(donante), texto).donativo
    receptor = next(r for r in receptores if r.id == d.receptor_id)
    servicios.distribucion.aceptar(actor_de(receptor), d.id)
    servicios.distribucion.iniciar_recoleccion(actor_de(recolector), d.id)
    return servicios.distribucion.confirmar_entrega(actor_de(recolector), d.id), receptor


@pytest.fixture
def entregado(servicios, actor_de, donante, receptores, recolector):
    return entregar(servicios, actor_de, donante, receptores, recolector)


def test_la_constancia_es_un_pdf_con_folio_y_total(servicios, actor_de, donante, entregado):
    d, receptor = entregado
    pdf = servicios.reportes.constancia_pdf(actor_de(donante), d.id)
    assert pdf.startswith(b"%PDF")
    crudo = texto_pdf(servicios.reportes.constancia_pdf(actor_de(donante), d.id, comprimir=False))
    assert d.id in crudo and f"{d.kg_totales:g} kg" in crudo
    assert receptor.nombre in crudo and "no es un comprobante fiscal" in crudo


def test_la_ven_donante_receptor_y_coordinador(servicios, actor_de, coordinador, donante, entregado):
    d, receptor = entregado
    for actor in (actor_de(donante), actor_de(receptor), coordinador):
        assert servicios.reportes.constancia_pdf(actor, d.id).startswith(b"%PDF")


def test_participantes_ajenos_no_la_obtienen(servicios, actor_de, coordinador, receptores, recolector, entregado):
    d, receptor = entregado
    otro = next(r for r in receptores if r.id != receptor.id)
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.constancia_pdf(actor_de(otro), d.id)
    with pytest.raises(ErrorAutorizacion):  # el recolector no es parte del CAR-12
        servicios.reportes.constancia_pdf(actor_de(recolector), d.id)
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.constancia_pdf(None, d.id)


def test_solo_de_donativos_entregados(servicios, actor_de, coordinador, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    with pytest.raises(ErrorServicio, match="entregados"):
        servicios.reportes.constancia_pdf(actor_de(donante), d.id)
    with pytest.raises(ErrorServicio, match="No existe"):
        servicios.reportes.constancia_pdf(coordinador, "no-existe")


def test_reporte_esg_solo_para_el_coordinador(servicios, actor_de, coordinador, donante, entregado):
    pdf = servicios.reportes.reporte_impacto_pdf(coordinador, HOY - timedelta(days=30), HOY, comprimir=False)
    texto = texto_pdf(pdf)
    assert pdf.startswith(b"%PDF") and "Reporte de impacto (ESG)" in texto and donante.nombre in texto
    assert "WRAP" in texto and "FAO" in texto
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.reporte_impacto_pdf(actor_de(donante), HOY, HOY)


def test_textos_fuera_de_latin1_no_rompen_el_pdf(servicios, actor_de, coordinador, donante, receptores, recolector):
    servicios.participantes.registrar(
        coordinador, Receptor(id="rec-emoji", nombre="Comedor 🍲 → Centro ≤ 5 km", ubicacion=Ubicacion(lat=20.6741, lon=-103.3404))
    )
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    assert a_latin1("Comedor 🍲 → Centro ≤ 5 km") == "Comedor  -> Centro <= 5 km"
    assert d.id  # la publicación funciona con el nombre raro registrado
    pdf = servicios.reportes.reporte_impacto_pdf(coordinador, HOY, HOY)
    assert pdf.startswith(b"%PDF")


def test_template_method_fija_el_orden_y_no_toca_la_base():
    class DocumentoNuevo(GeneradorDocumento):
        titulo = "Documento nuevo"
        pasos: ClassVar[list[str]] = []

        def encabezado(self):
            self.pasos.append("encabezado")
            super().encabezado()

        def cuerpo(self):
            self.pasos.append("cuerpo")
            self.linea("Hola → mundo")

        def pie(self):
            self.pasos.append("pie")

    pdf = DocumentoNuevo().generar()  # sin servicios ni repositorios
    assert pdf.startswith(b"%PDF") and DocumentoNuevo.pasos == ["encabezado", "cuerpo", "pie"]


def test_constancia_sin_participantes_usa_los_ids():
    d = Donativo(
        donante_id="don-x",
        texto_original="x",
        alimentos=[Alimento(nombre="pan", cantidad=1, unidad="kg", kg_estimados=1)],
    )
    crudo = ConstanciaEntrega(d, None, None, None, fecha_entrega=ahora(), comprimir=False).generar()
    texto = texto_pdf(crudo)
    assert "don-x" in texto and LEYENDA_CONSTANCIA[:40] in texto


# --------------------------------------------------------------- interfaz


def correr(servicios, actor, modulo):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        f"from ui import {modulo}\n"
        f"{modulo}.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicios"] = servicios
    app.session_state["prueba_actor"] = actor
    app.run()
    assert not app.exception
    return app


def botones_de_descarga(app) -> list:
    return list(app.get("download_button"))


def test_botones_de_descarga_en_las_tres_paginas(servicios, actor_de, coordinador, donante, entregado):
    _, receptor = entregado
    assert botones_de_descarga(correr(servicios, actor_de(receptor), "receptor"))
    assert botones_de_descarga(correr(servicios, actor_de(donante), "donante"))
    assert botones_de_descarga(correr(servicios, Actor(rol=Rol.COORDINADOR), "coordinador"))
