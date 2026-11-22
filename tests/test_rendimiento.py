"""El script de rendimiento: cálculos, tabla y que nunca invente un resultado."""

from __future__ import annotations

import pytest

from rescate.llm.cliente import ErrorLLM
from scripts import medir_rendimiento as mr


def test_p95_y_resumen():
    valores = [float(i) for i in range(1, 21)]
    assert mr.p95(valores) == 19.0
    assert mr.p95([3.0]) == 3.0
    assert mr.resumen_tiempos([1.0, 2.0, 3.0]) == "media 2.00 s · p95 3.00 s · máx 3.00 s"


def test_tabla_markdown():
    tabla = mr.tabla([mr.Resultado("Algo", "≤ 1 s", "0.5 s", "sí")])
    assert tabla.splitlines()[2] == "| Algo | ≤ 1 s | 0.5 s | sí |"


def test_concurrencia_y_tablero_cumplen():
    assert mr.medir_concurrencia(hilos=4).cumple == "sí"
    tablero = mr.medir_tablero(repeticiones=1)
    assert tablero.cumple == "sí" and "donativos entregados" in tablero.detalle[0]


@pytest.fixture
def sin_ollama(monkeypatch):
    class Apagado:
        def __init__(self, *args, **kwargs): ...

        def generar_json(self, *args, **kwargs):
            raise ErrorLLM("modelo no encontrado")

        def embeber(self, textos):
            raise ErrorLLM("embeddings no disponibles")

    monkeypatch.setattr(mr, "ClienteOllama", Apagado)


def test_sin_modelo_queda_pendiente(sin_ollama):
    flujo = mr.medir_flujo(2)
    assert (flujo.resultado, flujo.cumple) == ("pendiente", "pendiente")
    assert "No se midió" in flujo.detalle[0]


def test_documento_marca_lo_pendiente(sin_ollama):
    texto = mr.documento([mr.medir_flujo(1), mr.Resultado("Otra", "meta", "1 s", "sí", ["nota"])])
    assert "| pendiente | pendiente |" in texto and "- **Otra:** nota" in texto
