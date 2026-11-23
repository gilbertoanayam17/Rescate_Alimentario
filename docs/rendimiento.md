# Rendimiento

Resultados de `python scripts/medir_rendimiento.py` contra las metas de la visión (secciones 7 y 9.3).
Este archivo lo escribe el script; no se edita a mano.

- Fecha: 22/11/2026 18:17
- Equipo: Windows 11, 8 núcleos, Python 3.13.7
- Perfil del `.env`: `ligero` (modelo `gemma4:e4b`, embeddings `nomic-embed-text`)

| Medición | Meta | Resultado | Cumple |
| --- | --- | --- | --- |
| Frase → asignación (20 corridas) | ≤ 60 s por corrida | media 124.55 s · p95 224.42 s · máx 237.34 s | no (13 sobre 60 s) |
| Tablero de impacto con un año de historial | ≤ 3 s | máx 0.015 s (5 repeticiones) | sí |
| Búsqueda en el RAG (20 consultas) | ≤ 2 s por consulta | media 0.02 s · p95 0.03 s · máx 0.03 s | sí |
| 10 publicaciones simultáneas (LLM falso) | ninguna perdida | 10 guardados de 10, 0 perdidos, 0 errores (0.50 s) | sí |

## Notas

- **Frase → asignación (20 corridas):** Modelo `gemma4:e4b` (perfil `ligero`); 12 asignados y 3 que pidieron aclaración. Frases de `tests/frases_interprete.json`.
- **Tablero de impacto con un año de historial:** 446 donativos entregados generados con `scripts/generar_historial.py` (semilla 42).
- **Búsqueda en el RAG (20 consultas):** Embeddings `nomic-embed-text` en Ollama; cargar o construir el índice tomó 5.7 s (no cuenta en la meta, se hace una vez al arrancar).
- **10 publicaciones simultáneas (LLM falso):** Las publicaciones se atienden una por una (candado de `ServicioPublicacion`).

## Contexto del equipo (nota agregada a mano)

- Esta corrida se hizo en un equipo **sin GPU NVIDIA visible**: Ollama ejecutó `gemma4:e4b` al 100 % en CPU (`ollama ps`). El script no detecta la GPU, por eso esta nota.
- Con el ciclo ReAct del Asignador, cada publicación hace varias llamadas al modelo; en CPU eso lleva la media a unos 2 minutos.
- Falta repetir `python scripts/medir_rendimiento.py` en un equipo con GPU para verificar la meta de 60 s.
