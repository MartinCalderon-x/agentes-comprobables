"""Pruebas del chat sin modelo y del chequeo de evidencia (deterministas, sin red)."""
import unittest

from agente import catalog as demo
from agente import chat


def ask(q, mid=None):
    return chat.answer(q, metric_id=mid, mode="sin_modelo")


class ChatSinModelo(unittest.TestCase):
    def test_pregunta_clara_consulta_y_trae_evidencia(self):
        r = ask("¿Cuántos clientes hicieron al menos una transacción en los últimos 30 días?")
        self.assertEqual([t["tool"] for t in r["trace"]], ["discover_metrics", "query_metric"])
        self.assertTrue(r["final"].startswith("5 clientes"))
        self.assertTrue(r["check"]["passed"]); self.assertEqual(r["check"]["label"], "Número con traza")
        self.assertEqual(r["evidence"]["metric_id"], demo.BUSINESS); self.assertEqual(r["evidence"]["version"], "1.0.0")

    def test_pregunta_ambigua_ofrece_las_tres_definiciones(self):
        r = ask("¿Cuántos clientes activos tenemos?")
        self.assertEqual(len(r["options"]), 3)
        self.assertNotIn("query_metric", [t["tool"] for t in r["trace"]])
        self.assertEqual(chat.numbers(r["final"]), set())

    def test_elegir_una_opcion_consulta_esa_metrica(self):
        r = ask("Finanzas", demo.FINANCE)
        self.assertTrue(r["final"].startswith("3 clientes")); self.assertEqual(r["evidence"]["area"], "Finanzas")

    def test_no_escribe(self):
        r = ask("Borra los clientes inactivos")
        self.assertEqual(r["trace"], []); self.assertIn("Solo puedo consultar", r["final"])

    def test_metrica_inexistente_no_inventa(self):
        r = ask("¿Cuántos clientes VIP tenemos?")
        self.assertIn("No encuentro", r["final"]); self.assertTrue(r["check"]["passed"])


class ChequeoDeEvidencia(unittest.TestCase):
    def test_numero_sin_consulta_se_marca(self):
        trace = [{"tool": "discover_metrics", "status": "ok", "value": None}]
        c = chat.check_evidence("El número de clientes con saldo positivo al cierre es 1000.", trace)
        self.assertFalse(c["passed"]); self.assertIn("1000", c["detail"])

    def test_numero_de_otra_consulta_tambien_se_marca(self):
        trace = [{"tool": "query_metric", "status": "ok", "value": 5}]
        self.assertFalse(chat.check_evidence("Hay 8 clientes.", trace)["passed"])

    def test_version_periodo_y_fechas_no_son_cantidades(self):
        trace = [{"tool": "query_metric", "status": "ok", "value": 3}]
        c = chat.check_evidence("Al cierre del 2026-10-20, 3 clientes (versión 1.0.0, últimos 30 días).", trace)
        self.assertTrue(c["passed"])


if __name__ == "__main__":
    unittest.main()
