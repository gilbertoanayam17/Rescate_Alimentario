# Segunda entrega — Rescate Alimentario

Borrador para la plataforma: completar el enlace del video y realizar la revisión visual final antes de enviar el viernes 6 de noviembre de 2026 a las 23:30.

Presentamos la primera versión funcional de Rescate Alimentario, una plataforma que conecta excedentes de pequeños comercios con comedores y albergues. El proyecto se alinea con el ODS 2, Hambre cero, y la meta 12.3 del ODS 12, orientada a reducir el desperdicio de alimentos. Esta entrega prioriza el flujo de registrar, evaluar, asignar y entregar una donación.

El donante describe sus alimentos en lenguaje natural. El agente Intérprete estructura la información y solicita aclaraciones cuando faltan datos. El agente de Inocuidad combina reglas con recuperación documental para producir un dictamen y explicar las condiciones aplicables. Los donativos clasificados como no aptos no pasan a la asignación.

El agente Asignador compara organizaciones receptoras mediante herramientas que calculan distancia, capacidad disponible, compatibilidad de horario y distribución reciente de alimentos. Se excluyen receptores que no aceptan los tipos de alimento, que ya rechazaron el donativo o que no cumplen la refrigeración requerida. Los puntajes los calcula el código; el modelo selecciona entre candidatos y justifica su decisión. Si falla o devuelve un identificador inválido, se utiliza el respaldo determinista.

El receptor puede aceptar o rechazar indicando un motivo. El rechazo activa una nueva asignación. Después de la aceptación, un recolector puede iniciar el traslado y confirmar la entrega. La interfaz del coordinador permite registrar participantes, consultar donativos sin receptor, revisar el historial de estados y visualizar métricas básicas. La bitácora permite consultar decisiones, herramientas utilizadas, resultados y errores de los agentes.

La solución utiliza Python, Streamlit, LangGraph, DuckDB y Ollama. Se aplican los patrones State, Repository, Facade y Strategy, además de reglas de inocuidad encadenadas. Para ejecutarla se instalan las dependencias, se configura `.env` y se inicia `streamlit run app.py`, siguiendo el README. Las pruebas automatizadas usan un cliente simulado y no requieren Ollama.

La verificación local aprobó 141 pruebas con cliente simulado, incluidas las pantallas. Un ensayo separado realizó nueve consultas reales con gemma4:26b y recuperación documental, sin recurrir al respaldo determinista. Se comprobó entrega tras reasignación, rechazo por inocuidad y aclaración de un alimento refrigerado.

El MVP utiliza participantes ficticios y selección de roles sin autenticación. Horario y capacidad son criterios de puntuación, por lo que el receptor debe revisar la propuesta antes de aceptarla. No incluye predicción, rutas optimizadas ni certificación sanitaria. La operación propuesta corresponde a una ONG o municipio con apoyo de patrocinadores.

Código y documentación: https://github.com/gilbertoanayam17/Rescate_Alimentario/tree/flujo-asignacion

Video: PENDIENTE — sustituir por el enlace después de grabar y revisar los permisos de acceso.
