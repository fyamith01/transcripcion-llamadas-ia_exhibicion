# Ejemplo ejecutable

Reproduce **la lógica que corre después de los modelos** con llamadas 100 % inventadas: máscara de espera, asignación de palabras a turnos, re-ajuste por puntuación, colapso de bucles, roles por saludo y formato diarizado. El ASR y la diarización están simulados, así que no necesitas GPU, Docker ni modelos.

## Quick path

Requisito: [uv](https://docs.astral.sh/uv/). Los scripts solo usan la biblioteca estándar.

```bash
cd ejemplo
uv run diarizar.py    # procesa las 3 llamadas sintéticas
uv run pruebas.py     # 16 pruebas unitarias
```

Resultado esperado para la primera llamada (una sola línea, cortada aquí para leerla):

```text
[00:00] AGENTE: Gracias por llamar a Línea Demo, le atiende Camila. ¿En qué le puedo ayudar?
[00:06] CLIENTE: Hola, buenas tardes. Quiero saber el estado de un pedido.
[00:11] AGENTE: ¿Me regala el número de pedido, por favor?
...
[00:21] HABLANTE_?: Gracias por ver el video.
[00:38] AGENTE: Gracias por esperar. Su pedido llega mañana en la tarde.
[00:42] CLIENTE: Perfecto, muchas gracias.
   · máscara: se silencian 16.3 s de 43.7 s
   · regla 1: '¿Me regala' pasa al turno siguiente
   · regla 2: 'tarde.' vuelve al turno anterior
   · roles: regla 'gracias por llamar a'
```

## Apaga cada paso y mira qué cambia

Cada mejora tiene su interruptor, igual que en el servicio. Así se hace el rollback sin tocar código.

| Comando | Qué vas a ver |
|---|---|
| `MASCARA_ESPERA=off uv run diarizar.py` | La música de espera forma un "hablante" y el agente y el cliente quedan fusionados en el otro |
| `REAJUSTE=off uv run diarizar.py` | `¿Me regala` queda pegado al cliente y `tarde.` empieza el turno del cliente |
| `COLAPSO_BUCLES=off uv run diarizar.py` | La placa dictada vuelve a tener doce `U,` seguidas |
| `FORMATO=plano uv run diarizar.py` | Texto corrido sin hablantes ni tiempos (el formato anterior) |
| `REGLAS_SALUDO="buenos días" uv run diarizar.py` | Sin regla que coincida no se adivinan roles: `speaker_1`, `speaker_2` |
| `MASCARA_UMBRAL=-0.1 uv run diarizar.py` | Umbral tan estricto que ninguna palabra es creíble: la máscara cede, deja oír todo el audio y la espera vuelve a mezclar a los hablantes |
| `MASCARA_UMBRAL=-0.2 uv run diarizar.py` | Umbral intermedio: se silencia también voz real y un turno del cliente queda como `HABLANTE_?` (el costo de calibrar de más) |

## Las 3 llamadas

| Llamada | Qué demuestra |
|---|---|
| `demo-001` | Espera musical con una alucinación típica del ASR, y dos cambios de turno corridos (uno por cada regla del re-ajuste) |
| `demo-002` | Llamada saliente: el cliente habla primero y aun así el rol sale bien; bucle del ASR al dictar una placa; `sí, sí, sí, sí` se respeta |
| `demo-003` | Ninguna regla se cumple: la regla compuesta `estoy buscando a + le llamo de` la dice a medias el cliente |

## Qué mirar en el código

| Concepto | Dónde |
|---|---|
| Palabras creíbles y relleno de huecos | `mascara_de_espera` |
| Diarizador simulado con 2 hablantes forzados | `diarizar_simulado` |
| Solape máximo y tolerancia de 0,5 s | `asignar_hablantes` |
| Reglas 1 y 2 del re-ajuste | `reajustar` |
| Unidades de 1 a 4 palabras repetidas | `colapsar_bucles` |
| Reglas con `\|` y `+`, sin tildes ni mayúsculas | `parsear_reglas`, `asignar_roles` |
| Interruptores validados al arrancar | `Config.desde_entorno` |
| Guiones con su "verdad de terreno" y el error inyectado | `llamadas_sinteticas.py` |

> [!NOTE]
> Este código está escrito desde cero para el repositorio. No es el código del servicio original (ver [AVISO.md](../AVISO.md)).
