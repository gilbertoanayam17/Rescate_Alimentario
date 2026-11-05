# Rescate Alimentario

Del sobrante de la fonda al comedor comunitario, con agentes de IA que corren en local.

Rescate Alimentario conecta a pequeños comercios de alimentos (fondas, panaderías, puestos de
mercado) con comedores comunitarios. El donante describe su excedente en una frase y un equipo
de agentes con un LLM local lo interpreta, verifica que sea apto para donarse y elige al
receptor más adecuado. Proyecto del Hackathon Agéntico 2026B de Diseño de Software (ITESO),
alineado al ODS 2 (Hambre cero) y a la meta 12.3 del ODS 12.

> Estado: MVP en construcción (segunda entrega, 6 de noviembre de 2026).

## Cómo correrlo

Requisitos: Python 3.11 o superior y [Ollama](https://ollama.com) instalado.

```powershell
git clone https://github.com/gilbertoanayam17/Rescate_Alimentario.git
cd Rescate_Alimentario
python -m venv .venv
.venv\Scripts\Activate.ps1          # en macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # en macOS/Linux: cp .env.example .env
ollama pull gemma4:e4b
ollama pull nomic-embed-text
streamlit run app.py
```

Sin Ollama, pon `USAR_LLM_FALSO=1` en `.env`: la app funciona con las reglas de respaldo.

## Arquitectura

| Capa | Carpeta | Qué hace |
| --- | --- | --- |
| Interfaz | `app.py`, `ui/` | Streamlit con selector de rol (donante, receptor, recolector, coordinador) |
| Fachada | `rescate/servicios.py` | Único punto de entrada para la interfaz; aplica el ciclo de vida |
| Orquestador | `rescate/orquestador.py` | Grafo de LangGraph: interpretar → evaluar → asignar |
| Agentes | `rescate/agentes/` | Intérprete, Inocuidad y Asignador, con bitácora de razonamiento |
| Herramientas | `rescate/herramientas/` | Cálculos deterministas: distancia, capacidad, puntuación |
| RAG | `rescate/rag/` | Búsqueda en la NOM-251-SSA1-2009 y criterios de donación |
| LLM | `rescate/llm/` | Abstracción del LLM; implementación con Ollama y una falsa para pruebas |
| Persistencia | `rescate/persistencia/` | Repositorios sobre DuckDB |

## Pruebas

```powershell
pytest
```

## Equipo

- Gilberto Anaya Mercado
- Alejandro Ortega Abbadie
