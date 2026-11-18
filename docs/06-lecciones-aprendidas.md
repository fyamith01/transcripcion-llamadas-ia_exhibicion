# 6. Lecciones aprendidas

**Cada problema real dejó una regla.** Están ordenadas de la infraestructura hacia el texto.

| # | Problema | Regla que dejó |
|---|---|---|
| 1 | El worker se detenía sin logs | Un timeout de Python no protege código nativo: vigila desde fuera |
| 2 | El healthcheck daba falsos positivos | Mide la señal que de verdad cambia mientras trabaja |
| 3 | La VRAM no volvía después de cada trabajo | Si una librería no libera, reinicia el proceso a propósito |
| 4 | La música de espera se volvía un hablante | Controla qué oye el modelo, no solo qué devuelve |
| 5 | Turnos corridos 1–2 palabras | Repara con una regla pequeña, acotada y con interruptor |
| 6 | Bucles del ASR | Fija los umbrales midiendo el habla real |
| 7 | Adivinar al agente cuando nadie saluda | Sin evidencia, no etiquetes |
| 8 | La configuración rápida perdía frases | Velocidad sin una muestra de calidad al lado no decide nada |

## 1. Un timeout de Python no protege código nativo

La primera versión se detenía en silencio: la cola sana, la base sana, cientos de trabajos esperando y el worker sin una sola línea de error. El proceso estaba **congelado dentro del kernel** (estado `D`, inmune incluso a `SIGKILL`) por un problema de la capa de virtualización con la GPU.

Ninguna protección reaccionó: el timeout de la cola usa una señal que Python solo atiende entre instrucciones, el `restart: always` solo actúa cuando el proceso muere y el healthcheck no reinicia por sí mismo. La salida fue sacar la inferencia de esa capa y, en la versión diarizada, desplegar sobre Linux nativo con un worker que **publica el trabajo en curso** para que un vigilante externo lo pueda medir.

## 2. Mide la señal que de verdad cambia

El primer healthcheck miraba el latido del worker de la cola. Pero el worker sin `fork` **no refresca ese latido mientras ejecuta un trabajo**: cualquier audio de más de dos minutos lo marcaba como enfermo. Ahora la salud combina tres señales propias: modelos cargados, edad del trabajo en curso y latido en reposo ([detalle](01-arquitectura.md#salud-del-worker)).

## 3. Reinicia a propósito

CTranslate2 reserva memoria de GPU que no devuelve entre trabajos. En lugar de pelear con eso dentro del proceso, el worker **sale limpio cada 500 trabajos** y Docker lo levanta. Entre trabajos solo quedan los pesos.

## 4. Controla qué oye el modelo

Con dos hablantes forzados, la espera musical ganaba un grupo propio y el agente y el cliente se fusionaban en el otro. Ajustar el clustering no lo arreglaba: el problema era la **entrada**. La [máscara de espera](02-nucleo-de-voz.md#máscara-de-espera) silencia lo que Whisper no transcribió con confianza, sin borrar ni una palabra del texto.

## 5. Reglas pequeñas, acotadas y con interruptor

Los cambios de turno caían 1–2 palabras corridos. La tentación era un modelo de alineación más complejo; bastó una regla de puntuación que **nunca mueve más de 2 palabras**, se midió en seco sobre todo el set (unas 60 mejoras de unas 70 correcciones) y tiene su `off` documentado con su costo conocido.

## 6. Los umbrales salen de medir el habla real

Para recortar bucles había que distinguir "U, U, U, …" ×40 de un "sí, sí, sí, sí" legítimo. Se midió: el habla real del set no pasó de 4 repeticiones, así que el umbral quedó en 5 y se conservan 3.

## 7. Sin evidencia, no etiquetes

La primera versión de los roles, si ningún saludo coincidía, suponía que **el primero en hablar era el agente**. En las llamadas salientes el cliente contesta primero ("¿Aló?"), así que esa suposición invertía los roles justo cuando más falta hacían. Ahora, sin coincidencia, los hablantes salen como `speaker_1` y `speaker_2`: una etiqueta neutra es mejor que una equivocada, porque la auditoría posterior confía en ella.

Las reglas de saludo también se calibraron con llamadas reales: una regla que "sonaba bien" nunca se cumplía porque los agentes usaban otra conjugación, y otra frase la decían tanto agentes como clientes; de ahí salieron las [reglas compuestas](02-nucleo-de-voz.md#roles-por-saludo).

## 8. Velocidad con una muestra de calidad al lado

Un haz en lugar de cinco daba 9–20 % de velocidad y llegó a quedar como valor por defecto. Los textos del benchmark mostraron preguntas completas del agente desaparecidas y puntuación perdida, que es justo lo que la auditoría necesita. Se revirtió ([detalle](03-despliegue-y-operacion.md#benchmark-velocidad-frente-a-calidad)).

## Volver al inicio

[← README](../README.md)
