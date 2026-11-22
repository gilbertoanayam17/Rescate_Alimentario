"""Autorización dentro de los servicios, recolección atómica y cola de publicaciones (fase F0).

Responden a las observaciones del profesor: el rol se valida en el servicio contra la base (no en
la barra lateral) y dos voluntarios no pueden quedarse con el mismo donativo.
"""
import threading
from pathlib import Path

import pytest

from rescate.dominio.enums import EstadoDonativo, Rol
from rescate.dominio.modelos import Actor, Receptor, Recolector, Ubicacion
from rescate.servicios import ErrorAutorizacion, ErrorServicio

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def aceptado(servicios, actor_de, donante, receptores):
    """Un donativo asignado y aceptado, listo para recoger. Regresa (donativo, receptor)."""
    d = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos").donativo
    receptor = next(r for r in receptores if r.id == d.receptor_id)
    servicios.distribucion.aceptar(actor_de(receptor), d.id)
    return d, receptor


# ------------------------------------------------------------------- autorización


def test_receptor_ajeno_no_acepta_ni_rechaza(servicios, actor_de, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos").donativo
    otro = next(r for r in receptores if r.id != d.receptor_id)
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.aceptar(actor_de(otro), d.id)
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.rechazar(actor_de(otro), d.id, "No es mío")


def test_solo_un_recolector_registrado_puede_tomar(servicios, actor_de, donante, aceptado):
    d, _ = aceptado
    with pytest.raises(ErrorAutorizacion):  # un donante
        servicios.distribucion.iniciar_recoleccion(actor_de(donante), d.id)
    with pytest.raises(ErrorAutorizacion):  # un recolector que no existe en la base
        servicios.distribucion.iniciar_recoleccion(Actor(rol=Rol.RECOLECTOR, participante_id="fantasma"), d.id)


def test_rol_falso_se_rechaza_porque_el_rol_sale_de_la_base(servicios, donante, aceptado):
    d, _ = aceptado
    impostor = Actor(rol=Rol.RECOLECTOR, participante_id=donante.id)  # dice ser recolector
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.iniciar_recoleccion(impostor, d.id)


def test_donante_no_cancela_donativos_ajenos(servicios, actor_de, coordinador, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos").donativo
    from rescate.dominio.modelos import Donante

    otro = Donante(id="don-otro", nombre="Otra fonda", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    servicios.participantes.registrar(coordinador, otro)
    with pytest.raises(ErrorAutorizacion):
        servicios.publicacion.cancelar(actor_de(otro), d.id)


def test_solo_el_coordinador_administra(servicios, actor_de, donante, receptores):
    nuevo = Receptor(nombre="Comedor nuevo", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    with pytest.raises(ErrorAutorizacion):
        servicios.participantes.registrar(actor_de(donante), nuevo)
    with pytest.raises(ErrorAutorizacion):
        servicios.participantes.eliminar(actor_de(donante), receptores[0].id)
    d = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos").donativo
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.reintentar_asignacion(actor_de(donante), d.id)
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.todos(actor_de(donante))


def test_participante_edita_solo_su_perfil(servicios, actor_de, receptores):
    propio, ajeno = receptores
    servicios.participantes.registrar(actor_de(propio), propio.model_copy(update={"capacidad_kg_dia": 80}))
    assert servicios.participantes.obtener(propio.id).capacidad_kg_dia == 80
    with pytest.raises(ErrorAutorizacion):
        servicios.participantes.registrar(actor_de(propio), ajeno.model_copy(update={"capacidad_kg_dia": 1}))


def test_solo_los_involucrados_ven_un_donativo(servicios, actor_de, coordinador, donante, receptores, recolector):
    d = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos").donativo
    assert servicios.reportes.donativo(actor_de(donante), d.id).id == d.id
    assert servicios.reportes.historial(coordinador, d.id)
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.bitacora_de(actor_de(recolector), d.id)


# ------------------------------------------------------------------ concurrencia


def test_dos_voluntarios_no_toman_el_mismo_donativo(servicios, coordinador, actor_de, aceptado, recolector):
    d, _ = aceptado
    segundo = Recolector(id="vol-dos", nombre="Segundo voluntario", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    servicios.participantes.registrar(coordinador, segundo)
    barrera = threading.Barrier(2)
    resultados: dict[str, str] = {}

    def tomar(voluntario):
        barrera.wait()
        try:
            servicios.distribucion.iniciar_recoleccion(actor_de(voluntario), d.id)
            resultados[voluntario.id] = "tomó"
        except ErrorServicio as e:
            resultados[voluntario.id] = str(e)

    hilos = [threading.Thread(target=tomar, args=(v,)) for v in (recolector, segundo)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert sorted(resultados.values()) == ["Otro voluntario ya tomó este donativo.", "tomó"]
    final = servicios.reportes.donativo(coordinador, d.id)
    ganador = next(k for k, v in resultados.items() if v == "tomó")
    assert final.estado == EstadoDonativo.EN_RECOLECCION and final.recolector_id == ganador


def test_el_repositorio_toma_de_forma_atomica(repos, aceptado, recolector):
    from rescate.dominio.enums import Evento
    from rescate.dominio.estados import aplicar_evento

    d, _ = aceptado
    leido = repos.donativos.obtener(d.id)
    primero, segundo = leido.model_copy(deep=True), leido.model_copy(deep=True)
    for copia, quien in ((primero, recolector.id), (segundo, "otro")):
        copia.recolector_id = quien
        aplicar_evento(copia, Evento.INICIAR_RECOLECCION)
    assert repos.donativos.tomar_para_recoleccion(primero) is True
    assert repos.donativos.tomar_para_recoleccion(segundo) is False  # leyó un estado ya viejo
    assert repos.donativos.obtener(d.id).recolector_id == recolector.id


def test_publicaciones_simultaneas_no_se_pierden(servicios, actor_de, donante, receptores):
    resultados, errores = [], []

    def publicar(i):
        try:
            resultados.append(servicios.publicacion.publicar(actor_de(donante), f"Me sobraron {i + 1} bolillos"))
        except Exception as e:  # noqa: BLE001
            errores.append(e)

    hilos = [threading.Thread(target=publicar, args=(i,)) for i in range(10)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert not errores
    ids = {r.donativo.id for r in resultados}
    assert len(ids) == 10
    assert {d.id for d in servicios.publicacion.donativos_de_donante(actor_de(donante))} == ids


# ------------------------------------------------------ reglas movidas al servicio


def test_no_se_cancela_un_donativo_aceptado(servicios, actor_de, donante, aceptado):
    d, _ = aceptado
    with pytest.raises(ErrorServicio, match="ya lo aceptó"):
        servicios.publicacion.cancelar(actor_de(donante), d.id)


def test_rechazar_exige_motivo(servicios, actor_de, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos").donativo
    receptor = next(r for r in receptores if r.id == d.receptor_id)
    with pytest.raises(ErrorServicio, match="motivo"):
        servicios.distribucion.rechazar(actor_de(receptor), d.id, "   ")


def test_recolector_no_disponible_no_toma(servicios, actor_de, coordinador, aceptado, recolector):
    d, _ = aceptado
    servicios.participantes.registrar(coordinador, recolector.model_copy(update={"disponible": False}))
    with pytest.raises(ErrorServicio, match="no disponible"):
        servicios.distribucion.iniciar_recoleccion(actor_de(recolector), d.id)


def test_no_se_elimina_un_participante_con_donativos(servicios, actor_de, coordinador, donante, receptores):
    servicios.publicacion.publicar(actor_de(donante), "Me sobraron 20 bolillos")
    with pytest.raises(ErrorServicio, match="historial"):
        servicios.participantes.eliminar(coordinador, donante.id)


# ---------------------------------------------------------------------------- SRP


def test_servicio_donativos_ya_no_existe():
    import re

    assert not (RAIZ / "rescate" / "servicios.py").exists()
    uso = re.compile(r"import[^\n]*ServicioDonativos|ServicioDonativos\(|class ServicioDonativos")
    for archivo in [RAIZ / "app.py", *RAIZ.joinpath("rescate").rglob("*.py"), *RAIZ.joinpath("ui").rglob("*.py")]:
        assert not uso.search(archivo.read_text(encoding="utf-8")), archivo
