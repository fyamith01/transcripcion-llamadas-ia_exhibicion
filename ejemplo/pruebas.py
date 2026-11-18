# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pruebas del ejemplo (biblioteca estándar). Uso: uv run pruebas.py"""
from __future__ import annotations

import unittest

from diarizar import (
    Config, Turno, asignar_roles, colapsar_bucles, formatear, marca_de_tiempo,
    parsear_reglas, procesar, reajustar,
)
from llamadas_sinteticas import LLAMADAS, Palabra


def turno(hablante: str, texto: str, t0: float = 0.0) -> Turno:
    palabras = [Palabra(t0 + i, t0 + i + 0.3, w, 0) for i, w in enumerate(texto.split())]
    return Turno(hablante, palabras)


class Reajuste(unittest.TestCase):
    def test_regla_1_mueve_la_cola_al_turno_siguiente(self):
        a, b = turno("g1", "Claro. ¿Me regala"), turno("g2", "el número de pedido?", 10)
        reajustar([a, b])
        self.assertEqual(a.texto, "Claro.")
        self.assertEqual(b.texto, "¿Me regala el número de pedido?")

    def test_regla_2_devuelve_la_cabeza_al_turno_anterior(self):
        a, b = turno("g1", "Su pedido llega mañana en la"), turno("g2", "tarde. Perfecto, gracias.", 10)
        reajustar([a, b])
        self.assertEqual(a.texto, "Su pedido llega mañana en la tarde.")
        self.assertEqual(b.texto, "Perfecto, gracias.")

    def test_no_toca_si_el_turno_anterior_cierra_frase(self):
        a, b = turno("g1", "Listo."), turno("g2", "correcto", 10)
        self.assertEqual(reajustar([a, b]), [])

    def test_no_mueve_mas_de_dos_palabras(self):
        a, b = turno("g1", "Ya lo tengo en pantalla"), turno("g2", "para que lo revise usted. Bien.", 10)
        self.assertEqual(reajustar([a, b]), [])

    def test_no_vacia_un_turno(self):
        a, b = turno("g1", "Bueno"), turno("g2", "sí.", 10)
        self.assertEqual(reajustar([a, b]), [])


class Bucles(unittest.TestCase):
    def palabras(self, texto: str) -> list[Palabra]:
        return turno("g1", texto).palabras

    def test_recorta_unidad_repetida_cinco_o_mas_veces(self):
        salida, n = colapsar_bucles(self.palabras("es U, U, U, U, U, U, U siete"))
        self.assertEqual(" ".join(p.texto for p in salida), "es U, U, U, siete")
        self.assertEqual(n, 1)

    def test_respeta_repeticiones_del_habla_real(self):
        salida, n = colapsar_bucles(self.palabras("sí, sí, sí, sí, con ella"))
        self.assertEqual(n, 0)
        self.assertEqual(len(salida), 6)

    def test_unidades_de_varias_palabras(self):
        texto = " ".join(["de la cárcel"] * 6)
        salida, _ = colapsar_bucles(self.palabras(texto))
        self.assertEqual(len(salida), 9)


class Roles(unittest.TestCase):
    def test_gana_quien_dice_el_saludo_aunque_hable_segundo(self):
        turnos = [turno("g1", "¿Aló?"), turno("g2", "Buenas, mi nombre es Ana.", 5)]
        roles, _ = asignar_roles(turnos, parsear_reglas("mi nombre es"))
        self.assertEqual(roles, {"g1": "CLIENTE", "g2": "AGENTE"})

    def test_ignora_mayusculas_y_tildes(self):
        turnos = [turno("g1", "LE DAMOS LA BIENVENIDA A la línea"), turno("g2", "Hola", 5)]
        roles, _ = asignar_roles(turnos, parsear_reglas("le damos la bienvenída a"))
        self.assertEqual(roles["g1"], "AGENTE")

    def test_regla_compuesta_exige_todas_las_frases(self):
        turnos = [turno("g1", "Estoy buscando a alguien de pagos."), turno("g2", "Sí.", 5)]
        roles, motivo = asignar_roles(turnos, parsear_reglas("estoy buscando a + le llamo de"))
        self.assertEqual(roles, {"g1": "speaker_1", "g2": "speaker_2"})
        self.assertIn("ninguna", motivo)


class Formato(unittest.TestCase):
    def test_marca_de_tiempo(self):
        self.assertEqual(marca_de_tiempo(65.9), "[01:05]")
        self.assertEqual(marca_de_tiempo(3725), "[1:02:05]")

    def test_une_turnos_contiguos_con_la_misma_etiqueta(self):
        texto = formatear([turno("g1", "Hola."), turno("g3", "Sí.", 2)], {"g1": "AGENTE", "g3": "AGENTE"})
        self.assertEqual(texto, "[00:00] AGENTE: Hola. Sí.")


class PuntaAPunta(unittest.TestCase):
    def test_la_espera_no_se_atribuye_a_nadie_con_mascara(self):
        texto, _ = procesar(LLAMADAS[0], Config())
        self.assertIn("HABLANTE_?: Gracias por ver el video.", texto)
        self.assertIn("CLIENTE: Hola, buenas tardes.", texto)

    def test_sin_mascara_agente_y_cliente_se_fusionan(self):
        texto, _ = procesar(LLAMADAS[0], Config(mascara=False))
        self.assertNotIn("CLIENTE: Hola", texto)

    def test_formato_plano_es_el_rollback(self):
        texto, _ = procesar(LLAMADAS[1], Config(formato="plano"))
        self.assertNotIn("AGENTE", texto)
        self.assertIn("U, U, U, U, U", texto)     # el plano no recorta bucles


if __name__ == "__main__":
    unittest.main(verbosity=2)
