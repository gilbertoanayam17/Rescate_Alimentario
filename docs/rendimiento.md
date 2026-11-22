# Rendimiento

Resultados de `python scripts/medir_rendimiento.py` contra las metas de la visión (secciones 7 y 9.3).
Este archivo lo escribe el script; no se edita a mano.

- Fecha: 22/11/2026 16:55
- Equipo: Windows 11, 8 núcleos, Python 3.13.7
- Perfil del `.env`: `ligero` (modelo `gemma4:e4b`, embeddings `nomic-embed-text`)

| Medición | Meta | Resultado | Cumple |
| --- | --- | --- | --- |
| Frase → asignación (20 corridas) | ≤ 60 s por corrida | pendiente | pendiente |
| Tablero de impacto con un año de historial | ≤ 3 s | máx 0.015 s (5 repeticiones) | sí |
| Búsqueda en el RAG (20 consultas) | ≤ 2 s por consulta | media 0.02 s · p95 0.03 s · máx 0.03 s | sí |
| 10 publicaciones simultáneas (LLM falso) | ninguna perdida | 10 guardados de 10, 0 perdidos, 0 errores (0.46 s) | sí |

## Notas

- **Frase → asignación (20 corridas):** No se midió: el modelo `gemma4:e4b` no respondió en este equipo (gemma4:e4b no produjo un Sonda válido: model 'gemma4:e4b' not found (status code: 404)).
- **Tablero de impacto con un año de historial:** 446 donativos entregados generados con `scripts/generar_historial.py` (semilla 42).
- **Búsqueda en el RAG (20 consultas):** Embeddings `nomic-embed-text` en Ollama; cargar o construir el índice tomó 5.9 s (no cuenta en la meta, se hace una vez al arrancar).
- **10 publicaciones simultáneas (LLM falso):** Las publicaciones se atienden una por una (candado de `ServicioPublicacion`).
