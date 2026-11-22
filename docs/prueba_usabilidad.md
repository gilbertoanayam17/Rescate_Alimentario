# Prueba de usabilidad

Protocolo para comprobar, con personas ajenas al equipo, que Rescate Alimentario se usa sin capacitación (visión, secciones 7 y 9.3). Meta principal: **publicar un excedente en 60 s o menos**.

> Estado: **pendiente de aplicar.** Las tablas de resultados se llenan con las sesiones reales; no se rellenan con datos supuestos.

## Participantes

- 5 personas ajenas al equipo (familiares o amigos), de preferencia con perfiles distintos: alguien que atiende un comercio, alguien que trabaja o colabora en un comedor y alguien poco familiarizado con aplicaciones.
- Mínimo aceptable si el tiempo no alcanza: 3 personas, documentándolo en "Hallazgos".
- Sin capacitación: solo se les dice qué es Rescate Alimentario en una frase y se les da la tarea.

## Preparación

1. Con Streamlit detenido: `python scripts/cargar_semilla.py --reiniciar` y `python scripts/generar_historial.py`.
2. `python -m streamlit run app.py` con el perfil del `.env` (de preferencia `gemma4:e4b`; anotar si se usa `USAR_LLM_FALSO=1`).
3. Tener a la mano los PIN de la demo (`PIN_DEMO`, `PIN_COORDINADOR`) y un cronómetro.
4. Antes de cada persona, cerrar sesión en la app.

## Tareas

Se lee cada tarea en voz alta, tal cual. El moderador no ayuda salvo que la persona se atore más de 2 minutos (se anota como "con ayuda").

| # | Rol | Tarea que se lee | Éxito cuando | Se mide |
| --- | --- | --- | --- | --- |
| T1 | Donante (Fonda Doña Lupe) | "Eres la dueña de una fonda y te sobró comida hoy. Avísale a la plataforma con tus propias palabras." | El donativo queda publicado (asignado o con aclaración contestada) | Tiempo desde que toca el cuadro de texto hasta ver el resultado (meta ≤ 60 s); si necesitó aclaración |
| T2 | Receptor (el comedor asignado en T1) | "Eres del comedor. Revisa si te llegó un donativo y acéptalo." | El donativo queda aceptado | Tiempo; errores |
| T3 | Recolector (Iván Ramírez) | "Eres voluntario. Pide la ruta sugerida y toma los donativos." | Los donativos quedan en recolección | Tiempo; si entendió el mapa y el orden |
| T4 | Coordinador | "Encuentra cuántos kilos se rescataron en el último año." | Dice la cifra de la pestaña Impacto | Tiempo; clics hasta llegar |

## Cuestionario SUS (opcional)

Al terminar, la persona califica de 1 (totalmente en desacuerdo) a 5 (totalmente de acuerdo):

1. Creo que me gustaría usar esta plataforma con frecuencia.
2. La encontré innecesariamente compleja.
3. Me pareció fácil de usar.
4. Creo que necesitaría ayuda de alguien con conocimientos técnicos para usarla.
5. Las funciones están bien integradas.
6. Hay demasiadas inconsistencias.
7. Creo que la mayoría aprendería a usarla muy rápido.
8. Me pareció muy difícil de usar.
9. Me sentí con confianza al usarla.
10. Necesité aprender muchas cosas antes de poder usarla.

Cálculo: en los reactivos impares se resta 1 a la respuesta; en los pares, la respuesta se resta de 5. La suma se multiplica por 2.5 (resultado de 0 a 100; 68 es el promedio de referencia).

## Resultados

| Persona | Perfil | T1 (s) | ¿Aclaración? | T2 (s) | T3 (s) | T4 (s) | Ayuda en | SUS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | | | | | | | | |
| P2 | | | | | | | | |
| P3 | | | | | | | | |
| P4 | | | | | | | | |
| P5 | | | | | | | | |

Resumen: T1 dentro de la meta en __ de __ personas; mediana de T1: __ s; SUS promedio: __.

## Hallazgos

| # | Qué pasó | Personas | Severidad (alta, media, baja) |
| --- | --- | --- | --- |
| | | | |

## Qué se corrigió

| Hallazgo | Cambio | PR |
| --- | --- | --- |
| | | |
