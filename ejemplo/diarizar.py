# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Post-proceso de una transcripción diarizada, con datos sintéticos y sin GPU.

El ASR (faster-whisper) y la diarización (NeMo) están SIMULADOS: las palabras y
sus tiempos salen de `llamadas_sinteticas.py`. Lo que sí es real es la lógica que
corre después de los modelos, en el mismo orden que el servicio:

    1. máscara de espera     qué audio "oye" la diarización
    2. diarización simulada  turnos con cambios de turno corridos a propósito
    3. asignación            cada palabra al turno con el que más se solapa
    4. re-ajuste             mueve hasta 2 palabras para no partir una frase
    5. colapso de bucles     "U, U, U, U, U, U, ..." -> "U, U, U,"
    6. roles por saludo      quien dice el saludo es AGENTE; el otro, CLIENTE
    7. formato               una línea: [mm:ss] AGENTE: ... [mm:ss] CLIENTE: ...

Uso:
    uv run diarizar.py                         # las 3 llamadas de ejemplo
    FORMATO=plano uv run diarizar.py           # rollback: texto sin hablantes
    MASCARA_ESPERA=off uv run diarizar.py      # mira qué pasa sin la máscara
    REAJUSTE=off uv run diarizar.py            # cambios de turno sin corregir
    REGLAS_SALUDO="buenos días" uv run diarizar.py
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field

from llamadas_sinteticas import LLAMADAS, Llamada, Palabra

# ---------------------------------------------------------------------------
# Configuración por variables de entorno (cada paso se puede apagar)
# ---------------------------------------------------------------------------

REGLAS_POR_DEFECTO = (
    "gracias por llamar a | le damos la bienvenida a | mi nombre es | "
    "estoy buscando a + le llamo de"
)

DESCONOCIDO = "HABLANTE_?"
FIN_DE_FRASE = (".", "?", "!", "…")


@dataclass(frozen=True)
class Config:
    formato: str = "diarizado"          # "diarizado" | "plano"
    mascara: bool = True
    umbral_logprob: float = -0.5        # ventanas por debajo no son voz creíble
    reajuste: bool = True
    colapso: bool = True
    reglas: str = REGLAS_POR_DEFECTO

    @classmethod
    def desde_entorno(cls) -> "Config":
        def interruptor(nombre: str) -> bool:
            valor = os.environ.get(nombre, "on").strip().lower()
            if valor not in ("on", "off"):
                raise SystemExit(f"{nombre} debe ser 'on' u 'off', no {valor!r}")
            return valor == "on"

        formato = os.environ.get("FORMATO", "diarizado").strip().lower()
        if formato not in ("diarizado", "plano"):
            raise SystemExit(f"FORMATO debe ser 'diarizado' o 'plano', no {formato!r}")
        umbral = float(os.environ.get("MASCARA_UMBRAL", "-0.5"))
        if umbral > 0:
            raise SystemExit("MASCARA_UMBRAL debe ser <= 0")
        return cls(
            formato=formato,
            mascara=interruptor("MASCARA_ESPERA"),
            umbral_logprob=umbral,
            reajuste=interruptor("REAJUSTE"),
            colapso=interruptor("COLAPSO_BUCLES"),
            reglas=os.environ.get("REGLAS_SALUDO", REGLAS_POR_DEFECTO),
        )


@dataclass
class Turno:
    hablante: str
    palabras: list[Palabra] = field(default_factory=list)

    @property
    def inicio(self) -> float:
        return self.palabras[0].inicio

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


# ---------------------------------------------------------------------------
# 1. Máscara de espera
# ---------------------------------------------------------------------------

def mascara_de_espera(llamada: Llamada, umbral: float, margen: float = 0.25,
                      max_palabra: float = 1.5) -> list[tuple[float, float]]:
    """Intervalos de audio que la diarización sí debe oír.

    Una palabra es creíble si dura poco (la música produce "palabras" de varios
    segundos) y su ventana de Whisper tiene buena confianza. Todo lo demás se
    pone en cero antes de diarizar; la transcripción no pierde ninguna palabra.
    """
    confianza = {n: i.logprob for n, i in enumerate(llamada.intervenciones)}
    creibles = [
        (p.inicio - margen, p.fin + margen)
        for p in llamada.palabras
        if p.fin - p.inicio <= max_palabra and confianza[p.ventana] >= umbral
    ]
    if not creibles:                 # nada creíble: mejor oír todo que nada
        return [(0.0, llamada.palabras[-1].fin)]
    unidos = [creibles[0]]
    for ini, fin in creibles[1:]:
        if ini - unidos[-1][1] < 1.0:    # rellena huecos cortos
            unidos[-1] = (unidos[-1][0], max(fin, unidos[-1][1]))
        else:
            unidos.append((ini, fin))
    return unidos


def se_oye(ini: float, fin: float, mascara: list[tuple[float, float]]) -> bool:
    return any(ini < m_fin and fin > m_ini for m_ini, m_fin in mascara)


# ---------------------------------------------------------------------------
# 2. Diarización simulada (en el servicio real: VAD + embeddings + clustering)
# ---------------------------------------------------------------------------

def diarizar_simulado(llamada: Llamada,
                      mascara: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
    """Devuelve turnos (inicio, fin, grupo) como los entregaría un diarizador.

    Simula dos defectos reales:
    - El cambio de turno cae corrido 1-2 palabras (`corrimiento` del guion).
    - Con 2 hablantes forzados, si la música de espera se oye, forma su propio
      grupo y el agente y el cliente terminan juntos en el otro.
    """
    oidas = [i for i in llamada.intervenciones
             if se_oye(i.palabras[0].inicio, i.palabras[-1].fin, mascara)]
    fuentes = list(dict.fromkeys(i.quien for i in oidas))
    if "espera" in fuentes:
        grupo = {f: ("g2" if f == "espera" else "g1") for f in fuentes}
    else:
        grupo = {f: f"g{n + 1}" for n, f in enumerate(fuentes)}

    limites = [[i.palabras[0].inicio, i.palabras[-1].fin] for i in oidas]
    for n in range(1, len(oidas)):
        k = oidas[n].corrimiento
        previa, actual = oidas[n - 1].palabras, oidas[n].palabras
        if k > 0:      # el turno nuevo empieza tarde: el anterior se queda k palabras
            limites[n - 1][1] = actual[k - 1].fin
            limites[n][0] = actual[k].inicio
        elif k < 0:    # el turno nuevo empieza antes: se lleva k palabras del anterior
            limites[n - 1][1] = previa[k - 1].fin
            limites[n][0] = previa[k].inicio
    return [(ini, fin, grupo[i.quien]) for (ini, fin), i in zip(limites, oidas)]


# ---------------------------------------------------------------------------
# 3. Asignación de hablante a cada palabra
# ---------------------------------------------------------------------------

def asignar_hablantes(palabras: list[Palabra],
                      turnos: list[tuple[float, float, str]],
                      tolerancia: float = 0.5) -> list[Turno]:
    """Cada palabra va al turno con el que más se solapa; si no toca ninguno,
    al más cercano a <= `tolerancia` s; si no, queda como HABLANTE_?."""
    resultado: list[Turno] = []
    for p in palabras:
        solapes = [(min(p.fin, fin) - max(p.inicio, ini), h) for ini, fin, h in turnos]
        mejor, hablante = max(solapes, default=(0.0, DESCONOCIDO))
        if mejor <= 0:
            distancias = [(min(abs(p.inicio - fin), abs(ini - p.fin)), h)
                          for ini, fin, h in turnos]
            cerca, h = min(distancias, default=(tolerancia + 1, DESCONOCIDO))
            hablante = h if cerca <= tolerancia else DESCONOCIDO
        if resultado and resultado[-1].hablante == hablante:
            resultado[-1].palabras.append(p)
        else:
            resultado.append(Turno(hablante, [p]))
    return resultado


# ---------------------------------------------------------------------------
# 4. Re-ajuste de turnos por puntuación
# ---------------------------------------------------------------------------

def termina_frase(palabra: str) -> bool:
    return palabra.endswith(FIN_DE_FRASE)


def empieza_en_minuscula(palabra: str) -> bool:
    letras = [c for c in palabra if c.isalpha()]
    return bool(letras) and letras[0].islower() and palabra[0] not in "¿¡"


def inicia_frase(palabras: list[str], i: int) -> bool:
    w = palabras[i]
    if w[0] in "¿¡":
        return True
    if w[0].isupper() and not any(c.isdigit() for c in w):
        return True
    return i > 0 and termina_frase(palabras[i - 1])


def reajustar(turnos: list[Turno], maximo: int = 2) -> list[str]:
    """Corrige cambios de turno que parten una frase. Devuelve un registro.

    Solo actúa si el turno nuevo empieza en minúscula y el anterior no cierra
    con . ? ! … Regla 1: la cola del anterior (desde su último inicio de frase)
    pasa al nuevo. Regla 2: si no aplica, la cabeza del nuevo (hasta su primer
    fin de frase) pasa al anterior. Nunca más de `maximo` palabras y nunca deja
    un turno vacío.
    """
    registro = []
    for a, b in zip(turnos, turnos[1:]):
        if DESCONOCIDO in (a.hablante, b.hablante) or a.hablante == b.hablante:
            continue
        textos_a = [p.texto for p in a.palabras]
        textos_b = [p.texto for p in b.palabras]
        if not empieza_en_minuscula(textos_b[0]) or termina_frase(textos_a[-1]):
            continue
        inicio = max(i for i in range(len(textos_a)) if inicia_frase(textos_a, i) or i == 0)
        cola = len(textos_a) - inicio
        if 0 < cola <= maximo and inicio > 0:
            movidas = a.palabras[inicio:]
            del a.palabras[inicio:]
            b.palabras[:0] = movidas
            registro.append(f"regla 1: {' '.join(p.texto for p in movidas)!r} pasa al turno siguiente")
            continue
        fin = next((i for i, w in enumerate(textos_b) if termina_frase(w)), None)
        if fin is not None and fin + 1 <= maximo and fin + 1 < len(textos_b):
            movidas = b.palabras[: fin + 1]
            del b.palabras[: fin + 1]
            a.palabras.extend(movidas)
            registro.append(f"regla 2: {' '.join(p.texto for p in movidas)!r} vuelve al turno anterior")
    return registro


# ---------------------------------------------------------------------------
# 5. Colapso de bucles del ASR
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", sin_tildes.lower()).strip()


def colapsar_bucles(palabras: list[Palabra], minimo: int = 5,
                    conservar: int = 3) -> tuple[list[Palabra], int]:
    """Si una unidad de 1 a 4 palabras se repite `minimo` o más veces seguidas,
    deja solo `conservar` repeticiones. El habla real casi nunca pasa de 4."""
    claves = [normalizar(p.texto) for p in palabras]
    salida: list[Palabra] = []
    recortes = 0
    i = 0
    while i < len(palabras):
        for n in range(1, 5):
            unidad = claves[i:i + n]
            if len(unidad) < n or not any(unidad):
                continue
            reps = 1
            while claves[i + reps * n:i + (reps + 1) * n] == unidad:
                reps += 1
            if reps >= minimo:
                salida.extend(palabras[i:i + conservar * n])
                i += reps * n
                recortes += 1
                break
        else:
            salida.append(palabras[i])
            i += 1
    return salida, recortes


# ---------------------------------------------------------------------------
# 6. Roles por saludo
# ---------------------------------------------------------------------------

def parsear_reglas(texto: str) -> list[list[str]]:
    """'a | b + c' -> [['a'], ['b', 'c']]. `|` separa reglas; `+` une frases
    que el mismo hablante debe decir en la llamada."""
    reglas = []
    for regla in texto.split("|"):
        frases = [normalizar(f) for f in regla.split("+") if normalizar(f)]
        if frases:
            reglas.append(frases)
    return reglas


def contiene_frase(texto: str, frase: str) -> bool:
    return f" {frase} " in f" {texto} "      # palabras completas


def asignar_roles(turnos: list[Turno], reglas: list[list[str]]) -> tuple[dict[str, str], str]:
    """Gana la primera regla (en orden) que cumpla algún hablante. Ese hablante
    es AGENTE y los demás CLIENTE. Sin coincidencia no se adivina nada."""
    orden = list(dict.fromkeys(t.hablante for t in turnos if t.hablante != DESCONOCIDO))
    dicho = {h: normalizar(" ".join(t.texto for t in turnos if t.hablante == h)) for h in orden}
    for regla in reglas:
        for h in orden:
            if all(contiene_frase(dicho[h], f) for f in regla):
                roles = {o: ("AGENTE" if o == h else "CLIENTE") for o in orden}
                return roles, f"regla {' + '.join(regla)!r}"
    return {h: f"speaker_{n + 1}" for n, h in enumerate(orden)}, "ninguna regla: sin roles"


# ---------------------------------------------------------------------------
# 7. Formato de salida
# ---------------------------------------------------------------------------

def marca_de_tiempo(segundos: float) -> str:
    s = int(segundos)
    h, m = divmod(s // 60, 60)
    return f"[{h}:{m:02d}:{s % 60:02d}]" if h else f"[{m:02d}:{s % 60:02d}]"


def formatear(turnos: list[Turno], roles: dict[str, str]) -> str:
    partes: list[tuple[str, Turno]] = []
    for t in turnos:
        etiqueta = roles.get(t.hablante, DESCONOCIDO)
        if partes and partes[-1][0] == etiqueta:       # une turnos contiguos
            partes[-1][1].palabras.extend(t.palabras)
        else:
            partes.append((etiqueta, Turno(t.hablante, list(t.palabras))))
    return " ".join(f"{marca_de_tiempo(t.inicio)} {e}: {t.texto}" for e, t in partes)


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def procesar(llamada: Llamada, cfg: Config) -> tuple[str, list[str]]:
    notas: list[str] = []
    if cfg.formato == "plano":                       # rollback: ni diarización ni roles
        return " ".join(p.texto for p in llamada.palabras), ["formato plano"]

    if cfg.mascara:
        mascara = mascara_de_espera(llamada, cfg.umbral_logprob)
        total = llamada.palabras[-1].fin
        oido = sum(f - i for i, f in mascara)
        notas.append(f"máscara: se silencian {max(total - oido, 0):.1f} s de {total:.1f} s")
    else:
        mascara = [(0.0, llamada.palabras[-1].fin)]

    turnos = asignar_hablantes(llamada.palabras, diarizar_simulado(llamada, mascara))
    if cfg.reajuste:
        notas += reajustar(turnos)
    if cfg.colapso:
        for t in turnos:
            t.palabras, recortes = colapsar_bucles(t.palabras)
            if recortes:
                notas.append(f"bucles recortados: {recortes}")
    turnos = [t for t in turnos if t.palabras]
    roles, motivo = asignar_roles(turnos, parsear_reglas(cfg.reglas))
    notas.append(f"roles: {motivo}")
    return formatear(turnos, roles), notas


def main() -> None:
    cfg = Config.desde_entorno()
    for llamada in LLAMADAS:
        texto, notas = procesar(llamada, cfg)
        print(f"── {llamada.id} · {llamada.descripcion}")
        print(texto)
        for nota in notas:
            print(f"   · {nota}")
        print()


if __name__ == "__main__":
    main()
