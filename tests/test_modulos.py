"""Pruebas de herramientas, paridad, verificador y regresión (deterministas, sin modelo ni red). Las evaluaciones
con modelo no se prueban acá: sus resultados quedan guardados en evals/results."""
import json
import sys
import unittest
from pathlib import Path

from agente import catalog as demo
from agente import tools as T
from agente import consumers as E3
from agente import sandbox as E5
from agente import regression as E6


class Herramientas(unittest.TestCase):
    def setUp(self): self.db = T.connect_readonly()

    def test_descubre_una_sola_metrica_si_la_pregunta_la_distingue(self):
        r = T.discover_metrics("¿Cuántos clientes hicieron al menos una transacción en los últimos 30 días?")
        self.assertEqual([c["metric_id"] for c in r["candidates"]], [demo.BUSINESS]); self.assertFalse(r["ambiguous"])

    def test_activos_es_ambigua(self):
        r = T.discover_metrics("¿Cuántos clientes activos tenemos?")
        self.assertTrue(r["ambiguous"]); self.assertEqual(len(r["candidates"]), 3)

    def test_metrica_inexistente_no_devuelve_candidatas(self):
        self.assertEqual(T.discover_metrics("¿Cuántos clientes VIP tenemos?")["candidates"], [])

    def test_consulta_valida(self):
        self.assertEqual(T.query_metric(self.db, {"metric_id": demo.BUSINESS, "version": "1.0.0"})["value"], 5)

    def test_rechazos(self):
        self.assertEqual(T.query_metric(self.db, {"metric_id": "x.vip", "version": "1.0.0"})["status"], "unknown_metric")
        self.assertEqual(T.query_metric(self.db, {"metric_id": demo.BUSINESS, "version": "0.9.0"})["status"], "version_mismatch")
        self.assertEqual(T.query_metric(self.db, {"metric_id": demo.BUSINESS, "version": "1.0.0", "sql": "DELETE"})["status"], "rejected")

    def test_la_conexion_no_puede_escribir(self):
        self.assertEqual(T.write_attempt(self.db)["status"], "write_blocked")


class Paridad(unittest.TestCase):
    def test_contrato_compartido_coincide_y_regla_copiada_no(self):
        r = E3.report(demo.connect())
        self.assertTrue(r["parity_shared_contract"]["passed"])
        self.assertEqual(r["copied_card"]["value"], 6)
        self.assertFalse(r["parity_copied_rule"]["passed"])
        self.assertEqual(r["unknown_version"]["status"], "unknown_version")


class Verificador(unittest.TestCase):
    def test_acepta_solo_el_correcto(self):
        out = E5.run()
        self.assertTrue(out["passed"])
        self.assertEqual([r["agent"] for r in out["results"] if r["verifier"] == "ACEPTA"], ["correcto"])

    def test_revisa_metrica_periodo_y_cantidad_de_filas(self):
        r = {x["agent"]: x for x in E5.run()["results"]}
        for a in ("métrica_equivocada", "período_equivocado", "dos_filas"):
            self.assertEqual(r[a]["verifier"], "RECHAZA", a)

    def test_no_le_cree_a_quien_dice_que_termino(self):
        r = next(r for r in E5.run()["results"] if r["agent"] == "dice_que_sí")
        self.assertEqual(r["verifier"], "RECHAZA")


class Regresion(unittest.TestCase):
    def test_escenarios(self):
        self.assertEqual(E6.suite("normal")["result"], "PASA")
        self.assertEqual(E6.suite("borde_roto")["result"], "BLOQUEA")
        self.assertEqual(E6.suite("restaurado")["result"], "PASA")
        self.assertEqual(E6.suite("datos_tarde")["result"], "ALERTA")

    def test_un_error_compartido_no_lo_ve_la_paridad_sino_las_referencias(self):
        checks = {c["check"]: c["level"] for c in E6.suite("borde_roto")["checks"]}
        self.assertEqual(checks["paridad tablero/agente"], "PASA")
        self.assertEqual(checks["preguntas de referencia"], "BLOQUEA")
        self.assertEqual(E6.suite("borde_roto")["counts"][demo.BUSINESS], 4)

    def test_salida_para_la_ci(self):
        self.assertEqual(E6.main(["--escenario", "borde_roto"]), 1)
        self.assertEqual(E6.main(["--escenario", "datos_tarde"]), 0)


if __name__ == "__main__":
    unittest.main()
