# Manual de uso del MVP

Cómo usar Rescate Alimentario con cada rol, qué frases probar y cómo resolver los problemas más
comunes. La instalación está en el [README](../README.md).

## Antes de empezar

Con el entorno virtual activo (`.venv\Scripts\Activate.ps1` en Windows) y Streamlit detenido:

```powershell
python scripts/cargar_semilla.py --reiniciar   # base limpia con los 15 participantes de demostración
python scripts/indexar_conocimiento.py         # índice del RAG con nomic-embed-text
python -m streamlit run app.py                 # http://localhost:8501
```

- En la barra lateral eliges el rol en *Entrar como* y el participante en *¿Quién eres?*. No hay inicio de sesión.
- Abajo de la barra lateral se ve el modelo en uso, por ejemplo "LLM local: gemma4:e4b". Si dice "Sin LLM", los agentes usan sus reglas de respaldo (`USAR_LLM_FALSO=1` u Ollama apagado).
- La primera publicación puede tardar cerca de un minuto mientras Ollama carga el modelo; después, unos segundos.

## Participantes de demostración

Todos son ficticios, con coordenadas aproximadas de Guadalajara.

| Rol | Participante | Datos relevantes |
| --- | --- | --- |
| Donante | Fonda Doña Lupe | Fonda, cierra a las 18:00 |
| Donante | Panadería La Espiga | Panadería, cierra a las 21:00 |
| Donante | Frutas y Verduras El Güero | Puesto de mercado, cierra a las 17:00 |
| Donante | Taquería Corona | Taquería, cierra a las 21:00 |
| Donante | Cremería Santa Tere | Cremería, cierra a las 18:00 |
| Donante | Panadería Tlaquepaque | Panadería, cierra a las 20:00 |
| Donante | Cocina Zapopan | Cocina económica, cierra a las 17:00 |
| Receptor | Comedor Comunitario Oblatos | 60 kg/día, con refrigerador, 08:00 a 21:00; no recibe carne cruda |
| Receptor | Casa Hogar San Pedro | 30 kg/día, sin refrigerador, 07:00 a 20:00; no recibe lácteos, carne cruda ni bebidas |
| Receptor | Albergue Las Juntas | 40 kg/día, con refrigerador, 09:00 a 22:00; recibe todos los tipos |
| Receptor | Banco Comunitario Zapopan | 200 kg/día, con refrigerador, 07:00 a 22:00; recibe todos los tipos |
| Receptor | Comedor Infantil | 25 kg/día, sin refrigerador, 07:00 a 15:00; solo comida preparada, frutas y verduras |
| Recolector | Iván Ramírez | Centro, en moto |
| Recolector | Mariana Torres | Tlaquepaque, en auto |
| Recolector | Luis de Zapopan | Zapopan, en bicicleta |

## Donante: publicar lo que sobró

1. Escribe en el chat lo que te sobró, como se lo dirías a alguien: "Me sobraron 15 bolillos y 5 kg de jitomate". Los botones de *Ejemplos rápidos* mandan tres frases de prueba.
2. Si falta un dato importante, como la hora de preparación o cómo se ha guardado un guisado, el asistente pregunta. Responde en el mismo chat; tu respuesta se agrega al mismo donativo. *Empezar de nuevo* descarta lo pendiente.
3. Al completarse ves la tabla de alimentos con los kilos estimados por el sistema, el dictamen de inocuidad con sus condiciones y fundamento, y el receptor asignado con su justificación.
4. *¿Cómo lo decidieron los agentes?* abre la bitácora con lo que pensó, consultó y decidió cada agente.
5. En *Mis donativos* está cada donativo con su historial de estados. Puedes cancelarlo mientras ningún receptor lo haya aceptado.

## Receptor: aceptar o rechazar

- Arriba ves los kilos comprometidos hoy contra tu capacidad, los donativos por confirmar y los kilos recibidos en la semana.
- **Por confirmar:** *Aceptar* lo deja listo para los recolectores. Para rechazar, escribe un motivo y pulsa *No podemos recibirlo*: el sistema busca otro receptor sin repetirte. Si ya no hay ninguno compatible, el caso pasa al coordinador.
- **En camino** y **Recibidos** muestran los donativos aceptados y los entregados.
- **Mi perfil:** tipos de alimento aceptados, capacidad, refrigeración, horario, personas atendidas y dirección. Los cambios afectan las asignaciones siguientes.

El sistema orienta sobre inocuidad; no certifica el alimento.

## Recolector: recoger y entregar

- **Listos para recoger:** donativos aceptados, con origen y destino, distancia en línea recta, hora límite, condiciones de manejo resaltadas y un mapa. *Voy por él* te lo asigna.
- **En curso:** pulsa *Entregado* al dejarlo con el receptor.
- **Historial:** kilos entregados y donativos completados.

El botón se desactiva si la ventana de recolección ya terminó o si tu perfil está marcado como no disponible.

## Coordinador: operar la red

- **Resumen:** kilos entregados, donativos activos, no aptos, casos sin receptor y una gráfica por estado.
- **Donativos:** todos los donativos, con filtro por estado y el historial de cada uno.
- **Sin receptor:** casos que el Asignador no pudo colocar, con el motivo de cada descarte. *Reintentar asignación* vuelve a correr el Asignador, por ejemplo después de dar de alta un comedor.
- **Participantes:** listas por rol, alta de donantes, receptores y recolectores, y eliminación. Un participante con donativos no se puede eliminar, para conservar el historial.
- **Bitácora:** las decisiones recientes de los agentes, con filtros por agente y por id de donativo.

## Frases de prueba

Probadas con `gemma4:e4b` sobre una base recién cargada, a las 12:00 y a las 17:00. La redacción de los dictámenes cambia de una corrida a otra; el tipo de dictamen se mantiene.

| Donante | Frase | Resultado esperado |
| --- | --- | --- |
| Fonda Doña Lupe | Tengo 2 charolas de pollo en mole | Pregunta hora y conservación. Con "lo hice hace una hora y lo tengo en el refri": apto con condiciones (7 °C o menos) |
| Fonda Doña Lupe | Me sobraron 15 bolillos y 5 kg de jitomate | Sin preguntas; apto o apto con condiciones (lavar el jitomate); 6.05 kg |
| Fonda Doña Lupe | Me quedaron 3 litros de leche que dejé afuera desde la mañana | No apto: más de 2 h a temperatura ambiente (CI-02) |
| Taquería Corona | 5 porciones de pozole calientito, lo hice hace media hora | Apto con condiciones: mantener arriba de 60 °C o refrigerar; recalentar a 74 °C |
| Frutas y Verduras El Güero | 15 bolis y kilo y medio de jitomate | Entiende 15 bolillos y 1.5 kg de jitomate |
| Cocina Zapopan | Tengo 10 tamales pero ya están agrios | Pregunta; luego no apto por señal de deterioro (CI-01) |
| Cremería Santa Tere | 1 kg de queso panela | Pregunta solo cómo se ha guardado; con "en el refri desde las 9": apto con condiciones |
| Taquería Corona | 2 kg de pollo crudo en el refri desde las 8 | Apto con condiciones; solo dos receptores lo aceptan, así que si ambos lo rechazan pasa a *Sin receptor* |

Evita probar "una docena de conchas" sola: el modelo la endurece a no apto por conservación desconocida, aunque el pan es de bajo riesgo. Está anotado para corregirse.

## Problemas comunes

| Síntoma | Causa y solución |
| --- | --- |
| `No module named 'dotenv'` o `'pydantic'` | El entorno virtual no está activo. Ejecuta `.venv\Scripts\Activate.ps1`; si PowerShell lo bloquea, antes `Set-ExecutionPolicy -Scope Process Bypass` |
| `cargar_semilla.py --reiniciar` no dice "Base borrada" | Streamlit sigue corriendo y tiene la base abierta. Detenlo con Ctrl+C y repite |
| La primera publicación tarda cerca de un minuto | Ollama está cargando el modelo. Para calentarlo: `ollama run gemma4:e4b "hola"` |
| Inocuidad no cita numerales de la NOM-251 | La app no pudo crear el índice al arrancar porque Ollama estaba apagado o falta `nomic-embed-text`. Revisa `ollama list`, descarga el modelo si hace falta y reinicia la app |
| La app tarda más en abrir después de correr `pytest` | Las pruebas dejan el índice del RAG con embeddings simulados y la app lo reconstruye sola al arrancar. Para evitar la espera, ejecuta antes `python scripts/indexar_conocimiento.py` |
| "No existe el donativo …" o el chat muestra mensajes viejos | La base se reinició con la pestaña abierta. Recarga la página con F5 |
| El mapa del recolector no carga | Las teselas del mapa necesitan internet; lo demás funciona sin conexión |
| Las horas o los límites de recogida no cuadran | El servidor debe usar la hora local del centro de México |
| Cambié `.env` y no pasa nada | Streamlit guarda el servicio en caché: detén la app y vuelve a abrirla |
