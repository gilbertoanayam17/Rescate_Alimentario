# Rescate Alimentario

[![pruebas](https://github.com/gilbertoanayam17/Rescate_Alimentario/actions/workflows/pruebas.yml/badge.svg)](https://github.com/gilbertoanayam17/Rescate_Alimentario/actions/workflows/pruebas.yml)

Del sobrante de la fonda al comedor comunitario, con agentes de IA que corren en local.

Rescate Alimentario conecta a pequeños comercios de alimentos (fondas, panaderías, puestos de
mercado) con comedores comunitarios. El donante describe su excedente en una frase y un equipo
de cinco agentes con un LLM local lo interpreta, verifica que sea apto para donarse (NOM-251),
elige al receptor, propone la ruta al voluntario y anticipa los excedentes de mañana. Proyecto
del Hackathon Agéntico 2026B de Diseño de Software (ITESO), alineado al ODS 2 (Hambre cero) y
a la meta 12.3 del ODS 12.

> Entrega final: martes 24 de noviembre de 2026.
> Video de la entrega final: **pendiente** (se agrega la liga el lunes 23 al subirlo).
> Video de la segunda entrega (MVP): <https://youtu.be/A0HnOscPrOA>

## Cómo correrlo

Requisitos: Python 3.11 o superior. [Ollama](https://ollama.com) se necesita para las decisiones
del modelo real; las pruebas automatizadas usan un cliente simulado.

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

Prepara la demostración con Streamlit detenido:

```powershell
python scripts/cargar_semilla.py --reiniciar   # 15 participantes ficticios, con el PIN de la demo
python scripts/generar_historial.py            # un año de entregas: tablero de impacto y pronósticos
python scripts/indexar_conocimiento.py         # índice del RAG (requiere nomic-embed-text)
python -m streamlit run app.py                 # http://localhost:8501
```

Para probar sin modelo pon `USAR_LLM_FALSO=1` en `.env`: los agentes usan sus reglas de respaldo
(sirve para revisar reglas y pantallas, no demuestra decisiones de IA real).

**Inicio de sesión.** Elige tu rol y tu nombre y escribe tu PIN. Los participantes que carga
`cargar_semilla.py` entran con `PIN_DEMO` (por omisión `1234`) y el coordinador con
`PIN_COORDINADOR` (por omisión `0000`); los dos se cambian en `.env`. Un participante sin PIN no
puede entrar: el coordinador se lo asigna en la pestaña Participantes.

Para usar Ollama, revisa `ollama list`, pon `USAR_LLM_FALSO=0` y, si hace falta, descarga los modelos:

```powershell
ollama pull gemma4:e4b
ollama pull nomic-embed-text
ollama run gemma4:e4b "hola"    # calienta el modelo antes de la primera publicación
```

Reinicia Streamlit después de cambiar `.env`: los servicios se conservan en caché.

## Funcionalidad por caso de uso

| Caso de uso | Quién | Qué hace |
| --- | --- | --- |
| CU-01 Iniciar y cerrar sesión | Todos | PIN guardado con PBKDF2 y sal; 5 intentos fallidos bloquean 1 minuto; el rol sale del participante, no se elige. Aviso de privacidad en la entrada |
| CU-02 Publicar un excedente | Donante | Frase en lenguaje natural; el Intérprete pregunta lo que falte (hasta 2 aclaraciones). El texto del donante viaja como dato, nunca como instrucción |
| CU-03 Evaluar inocuidad | Agente de Inocuidad | 7 reglas (CI-01 a CI-07), RAG sobre la NOM-251 y LLM que solo puede endurecer el dictamen; los dudosos van al coordinador |
| CU-04 Asignar receptor | Agente Asignador | Filtros, puntuación con 4 criterios y ciclo ReAct de hasta 6 pasos con herramientas; respaldo a la selección entre los 3 mejores |
| CU-05 Aceptar o rechazar | Receptor | Rechazo con motivo y reasignación automática sin repetir al que rechazó |
| CU-06 Recibir avisos | Todos | Panel "🔔 Avisos" con cada cambio de estado que les toca |
| CU-07 Ruta y tomar donativos | Recolector | El Agente Logístico agrupa los donativos cercanos que caben en su transporte y ordena las paradas; la toma es atómica |
| CU-08 Confirmar la entrega | Recolector | Solo el voluntario que lleva el donativo |
| CU-09 Constancia de entrega | Donante, receptor, coordinador | PDF con folio, alimentos, kg, raciones, CO2e y dictamen |
| CU-10 Pronósticos | Donante, receptor | El Agente Predictor detecta patrones ("los lunes sobran guisados"), avisa y pre-reserva receptor; "Publicar ahora" desde el pronóstico |
| CU-11 Atender casos | Coordinador | Bandeja por tipo (sin receptor, posible inyección, inocuidad dudosa, vencido, rechazos repetidos) con reintentar, asignar a mano, cancelar y resolver |
| CU-12 Participantes | Coordinador; el receptor edita su perfil | Alta con PIN, edición, asignar PIN y baja (no se borra a quien tiene historial) |
| CU-13 Tablero de impacto | Coordinador; donante y receptor ven lo suyo | Kg, raciones y CO2e por periodo, donante y receptor; reporte ESG en PDF |
| CU-14 Historial y bitácora | Coordinador; donante los suyos | Transiciones de estado y razonamiento de cada agente |
| CU-15 Cancelar | Donante | Mientras ningún receptor lo haya aceptado |

El LLM decide; las herramientas calculan. La evaluación de inocuidad orienta; no constituye
certificación sanitaria. Los participantes de la demo son ficticios.

## Arquitectura

<!-- PENDIENTE: imagen docs/img/arquitectura_final.png, se genera con herramientas_docs (Gilberto). -->
> **Imagen de arquitectura final: pendiente** (`docs/img/arquitectura_final.png`). Mientras tanto,
> el diagrama de componentes está en [docs/uml/componentes.png](docs/uml/componentes.png).

| Capa | Carpeta | Qué hace |
| --- | --- | --- |
| Interfaz | `app.py`, `ui/` | Streamlit: entrada con PIN y una página por rol. Solo usa `Servicios` y siempre pasa el `Actor` de la sesión |
| Servicios | `rescate/servicios/` | `ServicioParticipantes`, `ServicioPublicacion` y `ServicioDistribucion` (una responsabilidad cada uno, observación SRP), más reportes, avisos, casos y pronósticos. Cada operación valida el `Actor` contra la base |
| Ciclo de vida y eventos | `rescate/servicios/ciclo_vida.py`, `eventos.py` | Transiciones (State), historial y eventos (Observer) que escuchan el notificador y el mediador |
| Mediador | `rescate/mediador.py` | Casos para el coordinador (Mediator); abre, no duplica y resuelve solo |
| Orquestador | `rescate/orquestador.py` | Grafo de LangGraph: interpretar → evaluar → asignar |
| Agentes | `rescate/agentes/` | Intérprete, Inocuidad, Asignador (ReAct), Logístico y Predictor, con bitácora y respaldo determinista |
| Herramientas | `rescate/herramientas/` | Cálculos deterministas: distancia, capacidad, horario, equidad, compatibilidad, puntuación, rutas, impacto y patrones |
| Documentos | `rescate/documentos/` | Constancia y reporte ESG en PDF (Template Method) |
| RAG | `rescate/rag/` | Búsqueda en la NOM-251-SSA1-2009 y criterios de donación (FAISS + `nomic-embed-text`) |
| LLM | `rescate/llm/` | `ClienteLLM` con Ollama y un cliente falso para pruebas |
| Persistencia | `rescate/persistencia/` | Repositorios sobre DuckDB |
| Composición | `rescate/contenedor.py` | Único lugar donde se crean y conectan las piezas |

Detalle, recorridos y decisiones: [docs/arquitectura.md](docs/arquitectura.md). Diagramas UML 2.5
(casos de uso, componentes, clases y secuencias): [docs/uml/](docs/uml/README.md).

## Patrones de diseño

| Patrón | Dónde |
| --- | --- |
| State | `rescate/dominio/estados.py` |
| Repository | `rescate/persistencia/repositorios.py` |
| Strategy (puntuación) | `rescate/herramientas/puntuacion.py` |
| Strategy (rutas) | `rescate/herramientas/rutas.py` |
| Strategy (canal de avisos) | `CanalAvisos` en `rescate/servicios/notificaciones.py` |
| Chain of Responsibility | `rescate/agentes/reglas_inocuidad.py` |
| Observer | `BusEventos` y `NotificadorEstados` en `rescate/servicios/` |
| Mediator | `MediadorCasos` en `rescate/mediador.py` |
| Template Method | `GeneradorDocumento` en `rescate/documentos/base.py` |
| ReAct | `AgenteAsignador` en `rescate/agentes/asignador.py` |
| Inversión de dependencias | `ClienteLLM`, `BaseConocimiento`, repositorios y `CanalAvisos` |
| Orquestación por grafo | `rescate/orquestador.py` |
| Raíz de composición | `rescate/contenedor.py` |
| SRP en servicios | `rescate/servicios/` (el antiguo `ServicioDonativos` se dividió) |

## Observaciones del profesor a la segunda entrega

| Observación | Cómo se atendió | Pruebas |
| --- | --- | --- |
| **SRP:** `ServicioDonativos` hacía participantes, publicación, asignación y entregas | Se dividió en `ServicioParticipantes`, `ServicioPublicacion` y `ServicioDistribucion`, más servicios de reportes, avisos, casos y pronósticos; `Servicios` solo los agrupa | `tests/test_autorizacion.py` (ningún módulo usa `ServicioDonativos`) |
| **Autorización:** el rol se elegía en la barra lateral y dos voluntarios podían tomar el mismo donativo | Cada servicio recibe el `Actor` y lo valida contra la base; la toma es atómica (`UPDATE … WHERE estado='asignado' AND recolector_id IS NULL`). Además, inicio de sesión con PIN: el rol ya no se elige | `tests/test_autorizacion.py` (rol falso, dos hilos con `Barrier`), `tests/test_sesion.py` |
| **Prompt injection** en el Intérprete | El texto del usuario se limpia y se delimita como dato (`seguridad_prompt.py`); se detectan intentos, se valida la respuesta del LLM con `detectar_conservacion()`, y se abre un caso para el coordinador | `tests/test_seguridad_prompt.py`; 0 de 10 manipulaciones exitosas con `gemma4:e4b` |

## Verificación

```powershell
python -m pytest                                      # sin Ollama (USAR_LLM_FALSO=1)
python scripts/evaluar_interprete.py                  # 50 frases con el LLM de .env
python scripts/evaluar_interprete.py --adversariales  # 10 intentos de manipulación
python scripts/medir_rendimiento.py                   # metas de rendimiento → docs/rendimiento.md
```

| Comprobación | Resultado |
| --- | --- |
| Suite con cliente simulado | 370 pruebas aprobadas, incluida `test_flujo_basico.py`; CI en GitHub Actions |
| Cobertura (coverage.py) | 96 % de `rescate/`, `ui/` y `app.py` |
| Intérprete con `gemma4:e4b` | 50 frases: 405 de 405 campos correctos (100 %; meta 90 %). Con `gemma4:26b`: 99.8 % |
| Prompt injection | 10 frases adversariales: 0 manipulaciones exitosas con `gemma4:e4b` y con `gemma4:26b` |
| Inocuidad | 51 casos: los 35 no aptos se rechazan (meta de la visión: 30) |
| Rendimiento | Tablero con un año de historial: 0.015 s (meta 3 s); RAG: p95 0.03 s (meta 2 s); 10 publicaciones simultáneas sin pérdidas. Frase → asignación con `gemma4:e4b`: ver [docs/rendimiento.md](docs/rendimiento.md) |
| Usabilidad | Protocolo con 5 personas en [docs/prueba_usabilidad.md](docs/prueba_usabilidad.md) |

## Impacto: fuentes de los factores

- Raciones: 0.42 kg por comida equivalente, WRAP (2020), guía de comidas equivalentes.
- Emisiones evitadas: 2.06 kg CO2e por kg, FAO (2013), *Food Wastage Footprint* (3.3 Gt CO2e / 1.6 Gt).

Ligas y detalle en [docs/arquitectura.md](docs/arquitectura.md#tablero-de-impacto-y-sus-fuentes).

## Modelos y datos

| Perfil (`PERFIL_MODELO`) | Modelo |
| --- | --- |
| `ligero` (por omisión, el del video) | `gemma4:e4b` |
| `completo` | `gemma4:26b` |
| `minimo` | `gemma4:e2b` |

`MODELO_LLM` tiene prioridad sobre el perfil. Los embeddings usan `nomic-embed-text`. Todo corre
en local: no se envían datos a servicios de IA externos. Las teselas del mapa necesitan internet.

## Operación y sostenibilidad

Una organización operadora (un municipio o una ONG, idealmente donataria autorizada o aliada de
un banco de alimentos) instala y opera la red. Los patrocinadores con metas ESG financian la
operación a cambio del reporte de impacto que la plataforma genera. Para donantes, comedores y
voluntarios es gratis. Los comercios tienen razones legales para participar: la Ley General de
la Alimentación Adecuada y Sostenible (art. 55) prohíbe desechar alimentos aptos, y la LISR
(art. 27, fr. XX) permite deducir la mercancía si antes se ofreció en donación. La constancia de
entrega sirve de respaldo, pero no es un comprobante fiscal (CFDI).

## Límites y trabajo futuro

- Distancias en línea recta; no hay ruteo vial ni tráfico.
- Avisos solo dentro de la app; WhatsApp o correo serían otra implementación de `CanalAvisos`.
- El bloqueo por intentos fallidos y el conteo de rechazos repetidos viven en memoria.
- El factor de emisiones es un promedio mundial, igual para todos los tipos de alimento.
- El servidor debe usar la hora local del centro de México (la base guarda horas sin zona).
- No usar para coordinar donaciones reales sin revisión legal y sanitaria adicional.

## Documentación

Índice completo en [docs/README.md](docs/README.md): visión y alcances, arquitectura, UML, manual
de uso, rendimiento, usabilidad, aviso de privacidad y texto de entrega.

## Licencia

El código se publica bajo la [licencia MIT](LICENSE). Los modelos (`gemma4` y `nomic-embed-text`)
conservan sus propias licencias, que se consultan en la [biblioteca de Ollama](https://ollama.com/library).

## Equipo

- Gilberto Anaya Mercado: publicar y evaluar (Intérprete, seguridad del prompt, Inocuidad, RAG,
  Agente Predictor y página del donante) y el contrato de servicios divididos.
- Alejandro Ortega Abbadie: asignar y entregar (Asignador ReAct, Agente Logístico y rutas,
  notificaciones, mediador de casos, impacto y documentos, inicio de sesión, páginas de receptor,
  recolector y coordinador), UML y documentación.
