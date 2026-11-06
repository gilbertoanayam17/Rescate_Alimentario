# Rescate Alimentario

Del sobrante de la fonda al comedor comunitario, con agentes de IA que corren en local.

Rescate Alimentario conecta a pequeños comercios de alimentos (fondas, panaderías, puestos de
mercado) con comedores comunitarios. El donante describe su excedente en una frase y un equipo
de agentes con un LLM local lo interpreta, verifica que sea apto para donarse y elige al
receptor más adecuado. Proyecto del Hackathon Agéntico 2026B de Diseño de Software (ITESO),
alineado al ODS 2 (Hambre cero) y a la meta 12.3 del ODS 12.

> MVP de la segunda entrega: viernes 6 de noviembre de 2026, 23:30 (centro de México).
> El video y su enlace siguen pendientes.

## Cómo correrlo

Requisitos: Python 3.11 o superior. [Ollama](https://ollama.com) se necesita para
las decisiones del modelo real; las pruebas automatizadas usan un cliente simulado.

En Windows (PowerShell), desde la carpeta del repositorio:

```powershell
git clone https://github.com/gilbertoanayam17/Rescate_Alimentario.git
cd Rescate_Alimentario
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

En macOS/Linux, los pasos equivalentes después de clonar son:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

Primero pon `USAR_LLM_FALSO=1` en `.env` para comprobar reglas y pantallas:

```powershell
python -m pytest
python -m streamlit run app.py
```

Abre http://localhost:8501. Detén la app con Ctrl+C antes de cambiar el modo,
indexar el conocimiento o ejecutar scripts sobre la misma base.

Para usar Ollama, revisa `ollama list`. Configura `MODELO_LLM` con un nombre
instalado y `USAR_LLM_FALSO=0` en `.env`. Si hace falta descargar modelos:

```powershell
ollama pull gemma4:e4b
ollama pull nomic-embed-text
python scripts/indexar_conocimiento.py --buscar "refrigeración"
python -m streamlit run app.py
```

Si ya tienes `gemma4:26b`, puedes usar `MODELO_LLM=gemma4:26b` sin descargar el
modelo ligero. Reinicia Streamlit después de cambiar `.env`: el servicio se conserva
en caché. Un índice generado con embeddings simulados se reconstruye al usar el cliente real.

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
python -m pytest
```

Verificación local del 5 de noviembre de 2026:

| Comprobación | Resultado |
| --- | --- |
| Suite con cliente simulado | 145 pruebas aprobadas; incluye `test_flujo_basico.py` |
| AppTest de Streamlit | Cuatro roles; rechazo con motivo, reasignación, aceptación, recolección, entrega, perfiles, altas, métricas, historial y filtros |
| Restricciones del asignador | Un no apto no se asigna; un id inventado o un receptor existente fuera del top 3 activa el respaldo |
| Ollama real, por la fachada de servicios | Nueve consultas con `gemma4:26b`, sin errores ni respaldo: entrega tras reasignación, leche no apta y aclaración de pollo refrigerado |
| RAG real | 24 fragmentos con `nomic-embed-text` y FAISS; búsqueda de refrigeración comprobada |
| Revisión visual en navegador | Pendiente, incluidas las teselas del mapa; AppTest comprueba comportamiento, no apariencia |

Entorno verificado: Python 3.13.7, Streamlit 1.67.0, DuckDB 2.0.0, Pydantic 2.14.3,
LangGraph 1.2.20, cliente Ollama 0.6.3 y pytest 9.2.0. Ruff comprobó imports,
estilo y errores estáticos de los archivos del flujo de asignación.

Ollama ejecutó `gemma4:26b` en CPU. Las consultas individuales del ensayo tardaron
entre 18 y 138 segundos; una publicación puede tardar varios minutos al encadenar
los agentes. Ensaya los tiempos en la computadora de grabación antes de producir
el video de 5 a 7 minutos.

## Funcionalidad del MVP

1. Publicar un excedente en lenguaje natural y responder preguntas de aclaración.
2. Evaluar inocuidad con reglas y recuperación documental; rechazar alimentos no aptos.
3. Clasificar receptores por distancia (35%), capacidad (25%), horario (25%) y equidad (15%).
   El modelo puede elegir entre los tres mejores compatibles; una salida inválida o un fallo
   activa el respaldo de mayor puntaje. Con un candidato no se consulta al modelo.
4. El receptor acepta o rechaza con motivo; al rechazar, se busca otro sin repetir el descartado.
5. Un recolector toma un donativo aceptado y registra su entrega.
6. El coordinador registra participantes, revisa casos sin receptor, métricas e historial.
7. La bitácora muestra decisiones, herramientas, resultados y fallos.

El LLM decide; las herramientas calculan. La app usa datos ficticios y un selector de roles,
sin autenticación. La evaluación de inocuidad orienta; no constituye certificación sanitaria.

### Publicar y evaluar: Intérprete e Inocuidad

- **Intérprete.** El LLM convierte la frase del donante en alimentos con un esquema Pydantic. Si a
  un perecedero le falta la hora de preparación o cómo se ha conservado, hace una sola pregunta
  (máximo dos rondas). Los kilos, las horas ("hace una hora") y el límite de recogida los calcula
  el código.
- **Reglas de inocuidad.** Una cadena de 7 reglas deterministas (Chain of Responsibility, criterios
  CI-01 a CI-07: deterioro, empaque, más de 2 h sin control de temperatura, origen desconocido,
  cadena de frío, comida caliente y vida útil). Si dicen no apto, ahí termina: el LLM no se
  consulta, porque nunca puede relajar un dictamen.
- **RAG.** Si el alimento pasa las reglas, el agente busca en extractos textuales de la
  NOM-251-SSA1-2009 (copiados del Diario Oficial de la Federación) y en los criterios del
  proyecto, con `nomic-embed-text` y FAISS; el LLM puede mantener o endurecer el dictamen.
- **Sin numerales inventados.** Solo se aceptan las citas del LLM que coinciden con la sección de
  un fragmento recuperado; las demás se descartan y quedan anotadas en la bitácora.

## Modelos y datos

Los perfiles se configuran en `.env`: `ligero`, `completo` o `minimo`. Los nombres exactos
están en `.env.example` y `rescate/config.py`. También se puede configurar `MODELO_LLM`.
Comprueba los modelos instalados con `ollama list`. Para trabajar sin modelo,
usa `USAR_LLM_FALSO=1`; este modo comprueba reglas y pantallas, no demuestra decisiones de IA real.

| Perfil | Modelo configurado |
| --- | --- |
| `ligero` | `gemma4:e4b` |
| `completo` | `gemma4:26b` |
| `minimo` | `gemma4:e2b` |

`MODELO_LLM` tiene prioridad sobre el perfil. Los embeddings usan `nomic-embed-text`.

Con Streamlit detenido, `python scripts/cargar_semilla.py` incorpora los 15 participantes
ficticios. `--reiniciar` borra la base de demostración: úsalo solo si deseas empezar de cero.
Para preparar la recuperación documental, ejecuta `python scripts/indexar_conocimiento.py`.
La instalación y el primer uso de modelos requieren internet; las teselas del mapa también.

## Patrones de diseño

| Patrón | Implementación |
| --- | --- |
| State | Ciclo de vida en `rescate/dominio/estados.py` |
| Facade | `ServicioDonativos`, utilizado por las pantallas |
| Repository | Persistencia en DuckDB |
| Strategy | Criterios de puntuación intercambiables |
| Chain of Responsibility | Reglas de inocuidad |
| Inversión de dependencias | Cliente LLM y repositorios por interfaces |
| Orquestación por grafo | LangGraph encadena los agentes |

## Operación y sostenibilidad

Una organización operadora (un municipio o una ONG, idealmente donataria autorizada o aliada de
un banco de alimentos que lo sea) instala y opera la red. Los patrocinadores con metas ESG
(ambientales, sociales y de gobernanza) financian la operación a cambio de reportes de impacto:
kilos rescatados y entregados, que la plataforma ya registra. Para donantes, comedores y
voluntarios es gratis.

Los comercios tienen razones legales para participar:

- La Ley General de la Alimentación Adecuada y Sostenible (DOF 17-04-2024), art. 55, prohíbe que
  los establecimientos comerciales desechen alimentos que se encuentren en condiciones de ser
  consumidos por los seres humanos, en los términos de su Reglamento.
- La Ley del Impuesto sobre la Renta, art. 27, fracción XX, permite deducir la mercancía que perdió
  su valor; tratándose de bienes básicos de alimentación, antes de destruirla debe ofrecerse en
  donación a instituciones autorizadas para recibir donativos deducibles.

Es una propuesta de operación: el MVP no tramita deducciones ni tiene acuerdos firmados, y el
beneficio fiscal depende del régimen de cada comercio y de que el receptor sea donataria autorizada.

## Límites y trabajo pendiente

- Horario y capacidad reducen puntaje, pero no excluyen candidatos. Por ello, una asignación
  es una propuesta que el receptor debe revisar: no garantiza espacio ni disponibilidad.
- Las distancias son en línea recta; no hay optimización vial ni estimación del tiempo de viaje.
- El servidor debe usar la hora local del centro de México: la base actual guarda horas sin zona.
- No hay login, notificaciones externas, predicción, comprobantes ni control de concurrencia
  diseñado para producción. No utilizar para coordinar donaciones reales sin revisión adicional.
- La versión implementa selección entre candidatos; el ciclo ReAct de varios pasos
  queda fuera de esta entrega.
- Pendientes: revisión visual y ensayo del video en el equipo de grabación, video y enlace.
- Para la entrega final del 24 de noviembre: UML de casos de uso, componentes, clases y
  secuencias; consolidación del alcance y video de todos los casos implementados.

## Guion breve de demo

1. Mostrar problema, usuarios y ODS (30 s).
2. Publicar un alimento apto, revisar el dictamen y la justificación del asignador (90 s).
3. Mostrar un alimento no apto y su regla (45 s).
4. Rechazar desde el receptor y aceptar desde el nuevo receptor (60 s).
5. Recoger y confirmar entrega (45 s).
6. Mostrar métricas, historial, bitácora y alta de un participante (60 s).
7. Explicar arquitectura, operación y pendientes (45 s).

Ensayar antes de grabar. El video debe distinguir las decisiones del modelo de los cálculos
del sistema y mostrar la configuración real utilizada. Enlace al video: pendiente.

## Equipo

- Gilberto Anaya Mercado: publicar y evaluar (Intérprete, Inocuidad, RAG y página del donante).
- Alejandro Ortega Abbadie: asignar y entregar (Asignador, herramientas, datos de demostración y
  páginas de receptor, recolector y coordinador).
