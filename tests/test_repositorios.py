"""Pruebas de persistencia en DuckDB. Archivo COMPARTIDO (fase 0)."""
from rescate.dominio.enums import Dictamen, EstadoDonativo, Rol, TipoEntradaBitacora
from rescate.dominio.modelos import (
    Alimento,
    Asignacion,
    DictamenInocuidad,
    Donante,
    Donativo,
    EntradaBitacora,
    Receptor,
    Ubicacion,
)
from rescate.persistencia.db import conectar
from rescate.persistencia.repositorios import BitacoraDuckDB, DonativosDuckDB, ParticipantesDuckDB


def test_participantes_conservan_su_clase():
    repo = ParticipantesDuckDB(conectar(":memory:"))
    repo.guardar(Donante(id="d1", nombre="Fonda", ubicacion=Ubicacion(lat=1, lon=2)))
    repo.guardar(Receptor(id="r1", nombre="Comedor", ubicacion=Ubicacion(lat=1, lon=2), tiene_refrigeracion=True))
    assert isinstance(repo.obtener("d1"), Donante)
    assert repo.receptores()[0].tiene_refrigeracion is True
    assert [p.id for p in repo.listar(Rol.DONANTE)] == ["d1"]
    repo.eliminar("d1")
    assert repo.obtener("d1") is None


def test_donativo_ida_y_vuelta_con_dictamen_y_asignacion():
    repo = DonativosDuckDB(conectar(":memory:"))
    d = Donativo(
        donante_id="d1",
        texto_original="3 kg de arroz",
        alimentos=[Alimento(nombre="arroz", cantidad=3, unidad="kg", kg_estimados=3)],
        dictamen=DictamenInocuidad(dictamen=Dictamen.APTO, motivo="ok"),
        asignacion=Asignacion(receptor_id="r1", justificacion="cerca"),
        estado=EstadoDonativo.ASIGNADO,
    )
    repo.guardar(d)
    leido = repo.obtener(d.id)
    assert leido == d
    assert repo.de_receptor("r1")[0].id == d.id
    assert repo.kg_asignados("r1") == 3
    repo.registrar_transicion(d.id, EstadoDonativo.EVALUADO, EstadoDonativo.ASIGNADO, "asignar", "cerca")
    assert repo.historial(d.id)[0]["nuevo"] == "asignado"


def test_bitacora_por_donativo():
    repo = BitacoraDuckDB(conectar(":memory:"))
    repo.agregar(EntradaBitacora(donativo_id="x", agente="Intérprete", tipo=TipoEntradaBitacora.PENSAMIENTO, contenido="hola", datos={"a": 1}))
    entradas = repo.de_donativo("x")
    assert entradas[0].contenido == "hola" and entradas[0].datos == {"a": 1}
    assert len(repo.recientes()) == 1


def test_bitacora_respeta_el_orden_de_insercion_dentro_del_mismo_segundo():
    """Entradas de agentes distintos anotadas en el mismo segundo salen en el orden real."""
    from datetime import datetime

    repo = BitacoraDuckDB(conectar(":memory:"))
    fecha = datetime(2026, 11, 5, 17, 0, 0)
    for agente, paso in [("Intérprete", 4), ("Intérprete", 5), ("Inocuidad", 1), ("Asignador", 1)]:
        repo.agregar(
            EntradaBitacora(
                donativo_id="x", agente=agente, paso=paso, tipo=TipoEntradaBitacora.RESULTADO,
                contenido=f"{agente} {paso}", fecha=fecha,
            )
        )
    orden = [e.contenido for e in repo.de_donativo("x")]
    assert orden == ["Intérprete 4", "Intérprete 5", "Inocuidad 1", "Asignador 1"]
    assert [e.contenido for e in repo.recientes(10)] == list(reversed(orden))
