"""Pruebas del RAG (base de conocimiento vectorial) con los embeddings por palabras del LLM falso."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rescate.config import cargar_configuracion
from rescate.llm.cliente import ErrorLLM
from rescate.llm.falso import ClienteLLMFalso
from rescate.rag import base_conocimiento as rag
from rescate.rag.base_conocimiento import (
    BaseConocimientoVacia,
    BaseConocimientoVectorial,
    crear_base_conocimiento,
    fragmentar,
)

CONOCIMIENTO = Path(__file__).resolve().parent.parent / "datos" / "conocimiento"


class LLMQueCuenta(ClienteLLMFalso):
    """LLM falso que cuenta cuántos textos le pidieron embeber."""

    def __init__(self) -> None:
        super().__init__()
        self.textos_embebidos = 0

    def embeber(self, textos: list[str]) -> list[list[float]]:
        self.textos_embebidos += len(textos)
        return super().embeber(textos)


class LLMSinEmbeddings(ClienteLLMFalso):
    def embeber(self, textos: list[str]) -> list[list[float]]:
        raise ErrorLLM("Ollama apagado")


CORPUS_CHICO = """# Corpus de prueba

## NOM-251-SSA1-2009, numeral 5.5.2: temperatura de los equipos de refrigeración

Los equipos de refrigeración se deben mantener a una temperatura máxima de 7°C.

## NOM-251-SSA1-2009, numeral 7.3.2: recalentamiento de alimentos preparados

Si se llegase a recalentar algún alimento preparado, debe alcanzar una temperatura de por lo menos 74°C (165°F).

## Criterio interno CI-01: señales de deterioro

Si el donante dice que el alimento huele mal o tiene moho, el donativo es no apto.
"""


@pytest.fixture
def corpus_chico(tmp_path) -> Path:
    destino = tmp_path / "chico"
    destino.mkdir()
    (destino / "prueba.md").write_text(CORPUS_CHICO, encoding="utf-8")
    return destino


@pytest.fixture
def carpeta(tmp_path) -> Path:
    destino = tmp_path / "conocimiento"
    shutil.copytree(CONOCIMIENTO, destino)
    return destino


def base(carpeta: Path, llm=None, **kwargs) -> BaseConocimientoVectorial:
    return BaseConocimientoVectorial(
        carpeta, carpeta.parent / "indice", llm or ClienteLLMFalso(), "falso", **kwargs
    )


def test_los_archivos_de_conocimiento_tienen_lo_que_pide_el_plan():
    nom = (CONOCIMIENTO / "nom251_extracto.md").read_text(encoding="utf-8")
    for numeral in ["5.5.2", "5.5.3", "7.3.1", "7.3.2", "7.3.3", "7.4.1"]:
        assert f"## NOM-251-SSA1-2009, numeral {numeral}:" in nom
    assert "https://sidof.segob.gob.mx/notas/docFuente/5133449" in nom
    criterios = (CONOCIMIENTO / "criterios_donacion.md").read_text(encoding="utf-8")
    for i in range(1, 8):
        assert f"## Criterio interno CI-0{i}:" in criterios
    assert "No son norma oficial" in criterios


def test_fragmentar_por_encabezados_y_parrafos_largos():
    largo = "\n\n".join(["palabra " * 100] * 4)  # ~3,200 caracteres en 4 párrafos
    md = f"# Título\n\nIntro que no se indexa\n\n## Sección A\n\nTexto corto.\n\n## Sección B\n\n{largo}\n"
    fragmentos = fragmentar(md, "prueba.md")
    assert fragmentos[0].seccion == "Sección A" and fragmentos[0].texto == "Texto corto."
    seccion_b = [f for f in fragmentos if f.seccion == "Sección B"]
    assert len(seccion_b) > 1 and all(len(f.texto) <= rag.MAX_CARACTERES for f in seccion_b)
    assert not any("Intro" in f.texto for f in fragmentos)


def test_buscar_refrigeracion_devuelve_primero_el_numeral_que_la_menciona(corpus_chico):
    resultados = base(corpus_chico).buscar("refrigeración 7 °C", k=4)
    assert (
        resultados[0].seccion
        == "NOM-251-SSA1-2009, numeral 5.5.2: temperatura de los equipos de refrigeración"
    )
    assert resultados[0].fuente == "prueba.md"
    assert [r.puntaje for r in resultados] == sorted((r.puntaje for r in resultados), reverse=True)
    assert len(resultados) == 3  # k se recorta al número de fragmentos


def test_el_indice_se_reusa_si_la_huella_no_cambia(carpeta):
    llm = LLMQueCuenta()
    primera = base(carpeta, llm)
    assert primera.reconstruido and llm.textos_embebidos == len(primera.fragmentos)

    llm.textos_embebidos = 0
    segunda = base(carpeta, llm)
    assert not segunda.reconstruido and llm.textos_embebidos == 0
    assert segunda.buscar("comida caliente")[0].seccion == primera.buscar("comida caliente")[0].seccion

    (carpeta / "nuevo.md").write_text("## Sección nueva\n\nTexto nuevo.\n", encoding="utf-8")
    tercera = base(carpeta, llm)
    assert tercera.reconstruido and len(tercera.fragmentos) == len(primera.fragmentos) + 1


def test_otro_cliente_llm_reconstruye(carpeta):
    base(carpeta, ClienteLLMFalso())
    assert base(carpeta, LLMQueCuenta()).reconstruido


def test_funciona_con_numpy_si_no_hay_faiss(corpus_chico, monkeypatch):
    monkeypatch.setattr(rag, "faiss", None)
    b = base(corpus_chico)
    assert b.motor == "numpy"
    assert (corpus_chico.parent / "indice" / "vectores.npy").exists()
    assert b.buscar("refrigeración 7 °C")[0].seccion.startswith("NOM-251-SSA1-2009, numeral 5.5.2")
    assert not base(corpus_chico).reconstruido  # también se reusa con NumPy


def test_sin_embeddings_la_fabrica_devuelve_base_vacia(carpeta, monkeypatch):
    monkeypatch.setenv("USAR_LLM_FALSO", "1")
    config = cargar_configuracion()
    from dataclasses import replace

    config = replace(config, ruta_conocimiento=carpeta, ruta_indice=carpeta.parent / "indice")
    assert isinstance(crear_base_conocimiento(config, LLMSinEmbeddings()), BaseConocimientoVacia)
    assert isinstance(crear_base_conocimiento(config, ClienteLLMFalso()), BaseConocimientoVectorial)


def test_carpeta_vacia_no_truena(tmp_path):
    b = BaseConocimientoVectorial(tmp_path / "no_existe", tmp_path / "indice", ClienteLLMFalso())
    assert b.buscar("leche") == [] and not b.disponible()
