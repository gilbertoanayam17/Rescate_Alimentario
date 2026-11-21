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


def test_avisos_por_destinatario_y_marcar_leido():
    from rescate.dominio.modelos import Aviso
    from rescate.persistencia.repositorios import AvisosDuckDB

    repo = AvisosDuckDB(conectar(":memory:"))
    a = Aviso(rol=Rol.RECEPTOR, destinatario_id="r1", titulo="Nuevo", mensaje="Hay un donativo")
    repo.agregar(a)
    repo.agregar(Aviso(rol=Rol.COORDINADOR, titulo="Caso", mensaje="Sin receptor"))
    assert [x.id for x in repo.de_destinatario(Rol.RECEPTOR, "r1")] == [a.id]
    assert len(repo.de_destinatario(Rol.COORDINADOR, None)) == 1
    assert repo.marcar_leido(a.id, Rol.RECEPTOR, "otro") is False
    assert repo.marcar_leido(a.id, Rol.RECEPTOR, "r1") is True
    assert repo.de_destinatario(Rol.RECEPTOR, "r1", solo_no_leidos=True) == []
    assert repo.de_destinatario(Rol.RECEPTOR, "r1")[0].leido is True


def test_casos_abiertos_sin_duplicar():
    from rescate.dominio.enums import EstadoCaso, TipoCaso
    from rescate.dominio.modelos import CasoEscalado
    from rescate.persistencia.repositorios import CasosDuckDB

    repo = CasosDuckDB(conectar(":memory:"))
    caso = CasoEscalado(tipo=TipoCaso.SIN_RECEPTOR, donativo_id="d1", motivo="nadie", emisor="Asignador")
    repo.guardar(caso)
    assert repo.abierto_de(TipoCaso.SIN_RECEPTOR, "d1").id == caso.id
    assert repo.abierto_de(TipoCaso.SIN_RECEPTOR, "d2") is None
    caso.estado = EstadoCaso.RESUELTO
    repo.guardar(caso)
    assert repo.abiertos() == [] and repo.de_donativo("d1")[0].estado == EstadoCaso.RESUELTO


def test_pronosticos_por_donante_receptor_y_dia():
    from datetime import date

    from rescate.dominio.modelos import Pronostico
    from rescate.persistencia.repositorios import PronosticosDuckDB

    repo = PronosticosDuckDB(conectar(":memory:"))
    p = Pronostico(
        donante_id="d1", fecha=date(2026, 11, 23), tipo="preparado", descripcion="guisados",
        kg_esperados=3, confianza=0.75, mensaje="Los lunes...", receptor_sugerido_id="r1",
    )
    repo.guardar(p)
    assert repo.obtener(p.id) == p
    assert repo.de_donante("d1", date(2026, 11, 22)) == [p]
    assert repo.de_receptor("r1", date(2026, 11, 24)) == []
    assert repo.del_dia(date(2026, 11, 23)) == [p]


def test_base_vieja_recibe_las_columnas_nuevas(tmp_path):
    import duckdb

    ruta = tmp_path / "vieja.duckdb"
    con = duckdb.connect(str(ruta))
    con.execute(
        "CREATE TABLE donativos (id VARCHAR PRIMARY KEY, donante_id VARCHAR NOT NULL, estado VARCHAR NOT NULL, "
        "datos VARCHAR NOT NULL, creado TIMESTAMP, actualizado TIMESTAMP)"
    )
    con.close()
    repo = DonativosDuckDB(conectar(ruta))
    d = Donativo(donante_id="d1", texto_original="pan", alimentos=[Alimento(nombre="pan", cantidad=1, kg_estimados=1)])
    repo.guardar(d)
    assert repo.obtener(d.id) == d
