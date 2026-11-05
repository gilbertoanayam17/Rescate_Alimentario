# Reglas para agentes de código: Rescate Alimentario

Proyecto del Hackathon Agéntico 2026B (Diseño de Software, ITESO). Rescate Alimentario lleva
los excedentes de comida de pequeños comercios a comedores comunitarios con agentes que usan
un LLM local (Ollama). ODS 2 (Hambre cero) y meta 12.3 del ODS 12.

Equipo y reparto por flujo:
- **Gilberto Anaya Mercado**, flujo 1 "Publicar y evaluar": Intérprete, Inocuidad, RAG y página del donante.
- **Alejandro Ortega Abbadie**, flujo 2 "Asignar y entregar": Asignador, herramientas, datos de demo y páginas de receptor, recolector y coordinador.

Cada integrante le da a su agente su plan de trabajo, que vive **fuera** de este repositorio.
**Los planes (`PLAN_*.md`) nunca entran al repo**: no los copies aquí, no los subas, no los cites
en commits, README, `docs/` ni código.

## Comandos (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
pytest                       # pruebas (no necesitan Ollama)
streamlit run app.py         # app en http://localhost:8501
```

Para trabajar sin Ollama, pon `USAR_LLM_FALSO=1` en `.env`.

## Reglas

1. **Modifica solo los archivos de tu flujo** (tabla de propiedad en tu plan). Los archivos
   marcados como COMPARTIDOS no se cambian sin autorización de tu humano; si se autoriza,
   el cambio debe ser mínimo y retrocompatible (agregar, no renombrar ni quitar) y va en un
   PR aparte con prefijo `contrato:`.
2. **Todo acceso al LLM pasa por `rescate.llm.cliente.ClienteLLM`** (`generar_json` con un
   modelo Pydantic, `embeber`). Nunca importes `ollama` fuera de `rescate/llm/`.
3. **El LLM decide; el código calcula.** Kg, distancias, capacidades, horas y puntajes los
   calculan funciones deterministas, nunca el modelo.
4. **Cada agente anota su razonamiento en la bitácora** (`self._anotar(...)`) y tiene un
   camino de respaldo determinista si recibe `ErrorLLM`.
5. **La inocuidad manda:** ante la duda, el dictamen más estricto. El LLM puede endurecer un
   dictamen de las reglas, nunca relajarlo.
6. Nombres del dominio en español, PEP 8, type hints y docstrings breves.
7. Antes de cada push: `pytest` en verde. Las pruebas de `tests/test_flujo_basico.py` deben
   seguir pasando siempre.
8. No subas `.env`, la base `.duckdb` ni el índice del RAG (`datos/indice/`).
9. Agrega archivos por nombre (`git add <archivo>`) y revisa `git status` antes de cada commit:
   si aparece un `PLAN_*.md` o `docs/plan/`, detente. `.gitignore` los bloquea por si acaso.
