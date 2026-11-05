from rescate.dominio.modelos import Receptor
from rescate.semilla import leer_semilla


def test_semilla_valida_y_conserva_ids():
    personas = leer_semilla("datos/semilla.json")
    ids = [p.id for p in personas]
    assert len(ids) == len(set(ids)) == 15
    assert {
        "don-lupe",
        "pan-espiga",
        "fru-guero",
        "com-oblatos",
        "casa-sanpedro",
        "alb-juntas",
        "rec-ivan",
        "rec-mariana",
    } <= set(ids)
    assert {p.tiene_refrigeracion for p in personas if isinstance(p, Receptor)} == {
        True,
        False,
    }
    assert all(
        20.55 <= p.ubicacion.lat <= 20.8 and -103.5 <= p.ubicacion.lon <= -103.2
        for p in personas
    )
