# Entrega final — Rescate Alimentario

Rescate Alimentario lleva el sobrante diario de fondas, panaderías y puestos de mercado a comedores comunitarios, alineado al ODS 2 (Hambre cero) y a la meta 12.3 del ODS 12. Esta entrega completa las doce características de la visión con cinco agentes sobre un LLM local (Ollama, `gemma4:e4b`).

Atendimos las tres observaciones de la segunda entrega. Por responsabilidad única, `ServicioDonativos` se dividió en servicios de participantes, publicación y distribución, más reportes, avisos, casos y pronósticos. La autorización vive en los servicios: cada operación recibe el actor y lo valida contra la base; la recolección es atómica y ahora se entra con PIN, así que el rol ya no se elige. Contra el prompt injection, el texto del donante se limpia y viaja delimitado como dato, los intentos se detectan y la respuesta del modelo se valida con `detectar_conservacion()`; ninguna de 10 frases adversariales logró manipularlo.

Los quince casos de uso están implementados: publicar con aclaraciones; evaluar inocuidad con reglas, RAG sobre la NOM-251 y un LLM que solo puede endurecer; asignar con un ciclo ReAct que consulta herramientas; aceptar o rechazar con reasignación; avisos en cada cambio de estado; ruta sugerida por el Agente Logístico; entrega con constancia en PDF; pronósticos con pre-reserva; bandeja de casos para el coordinador; tablero de impacto con kilos, raciones (WRAP) y CO2e evitado (FAO), con reporte ESG; participantes, historial, bitácora y cancelación.

Los patrones visibles son State, Repository, Strategy (puntuación, rutas y canal de avisos), Chain of Responsibility, Observer, Mediator, Template Method, ReAct, inversión de dependencias, orquestación con LangGraph y raíz de composición. Los diagramas UML 2.5 de casos de uso, componentes, clases y secuencias están en `docs/uml/`.

La verificación aprobó 370 pruebas sin Ollama, con 96 % de cobertura e integración continua en GitHub Actions. El Intérprete acertó 405 de 405 campos en 50 frases, los 35 casos no aptos se rechazan, el tablero responde en 0.015 s con un año de historial y diez publicaciones simultáneas se guardan sin pérdidas. Los tiempos de punta a punta con `gemma4:e4b` y la prueba de usabilidad están en `docs/rendimiento.md` y `docs/prueba_usabilidad.md`.

La guía para correrlo, con los PIN de la demo y el historial simulado, está en el README. La plataforma orienta sobre inocuidad, no certifica alimentos, y la constancia no sustituye un CFDI.

Código y documentación: <https://github.com/gilbertoanayam17/Rescate_Alimentario>

Video: **pendiente** (se agrega la liga al subirlo el lunes 23).
