"""Llamadas inventadas para el ejemplo. Ningún texto, nombre ni empresa es real.

Cada llamada es un guion: una lista de intervenciones con

- quien:       "A", "B" o "espera" (verdad de terreno que el pipeline NO ve)
- texto:       lo que "transcribió Whisper"
- logprob:     confianza media de la ventana de Whisper (avg_logprob, <= 0)
- corrimiento: error simulado de la diarización en el cambio de turno.
               +n = el turno nuevo empieza n palabras tarde (sus primeras
               palabras quedan en el turno anterior); -n = empieza n palabras
               antes (se lleva las últimas del turno anterior).

`construir()` convierte el guion en palabras con marcas de tiempo, como las que
entrega un ASR con `word_timestamps`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DURACION_PALABRA = 0.3      # s, voz normal
DURACION_ESPERA = 3.0       # s, "palabras" alucinadas sobre música
PAUSA_PALABRAS = 0.1
PAUSA_INTERVENCIONES = 0.6


@dataclass
class Palabra:
    inicio: float
    fin: float
    texto: str
    ventana: int            # índice de la intervención (ventana de Whisper)


@dataclass
class Intervencion:
    quien: str
    texto: str
    logprob: float = -0.2
    corrimiento: int = 0
    palabras: list[Palabra] = field(default_factory=list)


@dataclass
class Llamada:
    id: str
    descripcion: str
    intervenciones: list[Intervencion]

    @property
    def palabras(self) -> list[Palabra]:
        return [p for i in self.intervenciones for p in i.palabras]


def construir(id_: str, descripcion: str, guion: list[tuple]) -> Llamada:
    intervenciones = [Intervencion(*fila) for fila in guion]
    t = 0.5
    for n, inter in enumerate(intervenciones):
        dur = DURACION_ESPERA if inter.quien == "espera" else DURACION_PALABRA
        for texto in inter.texto.split():
            inter.palabras.append(Palabra(round(t, 2), round(t + dur, 2), texto, n))
            t += dur + PAUSA_PALABRAS
        t += PAUSA_INTERVENCIONES
    return Llamada(id_, descripcion, intervenciones)


LLAMADAS = [
    construir(
        "demo-001",
        "Entrante, con espera musical y dos cambios de turno corridos",
        [
            ("A", "Gracias por llamar a Línea Demo, le atiende Camila. ¿En qué le puedo ayudar?", -0.15),
            ("B", "Hola, buenas tardes. Quiero saber el estado de un pedido.", -0.20),
            ("A", "¿Me regala el número de pedido, por favor?", -0.18, +2),
            ("B", "Claro, es el cuatro cinco uno.", -0.25),
            ("A", "Un momento, por favor, la dejo en espera.", -0.20),
            ("espera", "Gracias por ver el video.", -1.10),
            ("A", "Gracias por esperar. Su pedido llega mañana en la tarde.", -0.22),
            ("B", "Perfecto, muchas gracias.", -0.20, -1),
        ],
    ),
    construir(
        "demo-002",
        "Saliente: el cliente contesta primero y Whisper entra en bucle al dictar una placa",
        [
            ("B", "¿Aló?", -0.30),
            ("A", "Buenas tardes, mi nombre es Andrés y le llamo de Línea Demo. ¿Hablo con la señora Marta?", -0.18),
            ("B", "Sí, sí, sí, sí, con ella.", -0.21),
            ("A", "La llamo para confirmar la placa del vehículo. ¿Me la repite?", -0.20),
            ("B", "Claro, es K L, U, U, U, U, U, U, U, U, U, U, U, U, siete tres.", -0.45),
            ("A", "Listo, quedó registrada. Que tenga buena tarde.", -0.19),
        ],
    ),
    construir(
        "demo-003",
        "Sin saludo reconocible: una regla compuesta se cumple a medias",
        [
            ("B", "Hola, estoy buscando a alguien del área de pagos.", -0.22),
            ("A", "Sí, señor. Cuénteme.", -0.20),
            ("B", "Quiero saber si ya llegó mi transferencia.", -0.24),
            ("A", "Ya aparece aplicada desde ayer.", -0.21),
        ],
    ),
]
