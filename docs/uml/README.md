# Diagramas UML 2.5

Fuente en PlantUML (`.puml`) y su imagen (`.png`) con el mismo nombre. Los nombres de clases, métodos y casos de uso son los del código en `main`.

| Diagrama | Archivo | Qué muestra |
| --- | --- | --- |
| Casos de uso | [casos_de_uso.puml](casos_de_uso.puml) | Los 4 roles y el sistema con sus agentes; CU-01 a CU-15. CU-02 incluye CU-03 y CU-04; CU-08 extiende CU-07; CU-06 lo disparan los demás. |
| Componentes | [componentes.puml](componentes.puml) | Interfaz, servicios, orquestador, agentes, herramientas, RAG, cliente LLM (Ollama), persistencia (DuckDB), documentos, mediador y bus de eventos, con sus interfaces. |
| Clases: dominio | [clases_dominio.puml](clases_dominio.puml) | Modelos, enums principales, estados (State) y repositorios (interfaces y DuckDB). |
| Clases: agentes y servicios | [clases_agentes_servicios.puml](clases_agentes_servicios.puml) | `Agente` y los 5 agentes, `ClienteLLM`, la cadena de reglas, las Strategy de puntuación y de rutas, `GeneradorDocumento` (Template Method), los servicios, Observer, Mediator y `CanalAvisos`. |
| Secuencia: publicar | [secuencia_publicar.puml](secuencia_publicar.puml) | El donante publica con aclaración → Intérprete → Inocuidad (reglas, RAG, LLM) → Asignador ReAct → ciclo de vida → avisos. |
| Secuencia: recolección | [secuencia_recoleccion.puml](secuencia_recoleccion.puml) | El receptor acepta → ruta sugerida → dos voluntarios intentan tomar (uno gana) → entrega → constancia. |
| Secuencia: seguridad | [secuencia_seguridad.puml](secuencia_seguridad.puml) | Texto malicioso → detección → validación con `detectar_conservacion` → caso al coordinador. |

## Cómo regenerar los PNG

Con Java instalado y el jar de PlantUML (o la extensión de PlantUML de VS Code). Los diagramas de clases, componentes y casos de uso usan `!pragma layout smetana`, así que no hace falta Graphviz:

```powershell
java -jar plantuml.jar -tpng docs/uml/*.puml
```
