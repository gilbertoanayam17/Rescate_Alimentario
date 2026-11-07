# Segunda entrega — Rescate Alimentario

Presentamos la primera versión funcional de Rescate Alimentario, una plataforma que conecta excedentes de pequeños comercios con comedores y albergues. El proyecto se alinea con el ODS 2, Hambre cero, y la meta 12.3 del ODS 12, orientada a reducir el desperdicio de alimentos. Esta entrega prioriza el flujo de registrar, evaluar, asignar y entregar una donación.

El donante describe sus alimentos en lenguaje natural. El agente Intérprete estructura la información y solicita aclaraciones cuando faltan datos. El agente de Inocuidad combina reglas con recuperación documental para producir un dictamen y explicar las condiciones aplicables. Los donativos clasificados como no aptos no pasan a la asignación.

El agente Asignador compara organizaciones receptoras mediante herramientas que calculan distancia, capacidad disponible, compatibilidad de horario y distribución reciente de alimentos. Se excluyen receptores que no aceptan los tipos de alimento, que ya rechazaron el donativo o que no cumplen la refrigeración requerida. Los puntajes los calcula el código; el modelo selecciona entre candidatos y justifica su decisión. Si falla o devuelve un identificador inválido, se utiliza el respaldo determinista.

El receptor puede aceptar o rechazar indicando un motivo. El rechazo activa una nueva asignación. Después de la aceptación, un recolector puede iniciar el traslado y confirmar la entrega. La interfaz del coordinador permite registrar participantes, consultar donativos sin receptor, revisar el historial de estados y visualizar métricas básicas. La bitácora permite consultar decisiones, herramientas utilizadas, resultados y errores de los agentes.

La solución utiliza Python, Streamlit, LangGraph, DuckDB y Ollama. Aplica ocho patrones: State (ciclo de vida), Facade (interfaz), Repository (persistencia), Strategy (criterios de asignación), Chain of Responsibility (reglas de inocuidad), inversión de dependencias (cliente del LLM), orquestación por grafo (LangGraph) y raíz de composición. La instalación está en el README.

La verificación local aprobó 171 pruebas con cliente simulado, incluidas las pantallas; los 35 casos no aptos de inocuidad se rechazan y, en 20 frases de prueba, el Intérprete con gemma4:e4b acertó el 100 % de los campos (meta: 90 %). Un ensayo aparte realizó nueve consultas reales con gemma4:26b sin recurrir al respaldo determinista; el video usa gemma4:e4b.

El MVP utiliza participantes ficticios y selección de roles sin autenticación. Horario y capacidad son criterios de puntuación, por lo que el receptor debe revisar la propuesta antes de aceptarla. No incluye predicción, rutas optimizadas ni certificación sanitaria. La operación la sostendría una ONG o municipio con patrocinadores con metas ESG; los comercios participan por el artículo 55 de la Ley General de la Alimentación Adecuada y Sostenible, que prohíbe desechar alimentos aptos, y la deducción del artículo 27, fracción XX, de la LISR.

Código y documentación: https://github.com/gilbertoanayam17/Rescate_Alimentario

Video: https://youtu.be/A0HnOscPrOA
