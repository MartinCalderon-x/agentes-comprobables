"""Pruebas del servidor: levanta app.py en un puerto libre y llama a la API como lo hace la pantalla.
El chat se prueba en modo sin modelo para que no dependa de LM Studio."""
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import app


class Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return r.status, r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read())

    def test_pantalla(self):
        status, body = self.get("/")
        self.assertEqual(status, 200); self.assertIn(b"Agentes", body)

    def test_tablero(self):
        d = json.loads(self.get("/api/tablero")[1])
        self.assertEqual([c["value"] for c in d["cards"]], [8, 5, 3]); self.assertTrue(d["parity"]["passed"])

    def test_chat(self):
        status, d = self.post("/api/chat", {"question": "¿Cuántos clientes tienen saldo positivo al cierre?", "mode": "sin_modelo"})
        self.assertEqual(status, 200); self.assertTrue(d["final"].startswith("3 clientes")); self.assertTrue(d["check"]["passed"])

    def test_chat_rechaza_metrica_desconocida(self):
        self.assertEqual(self.post("/api/chat", {"metric_id": "x.y"})[0], 400)

    def test_validacion(self):
        d = json.loads(self.get("/api/validar")[1])
        self.assertTrue(all(i["passed"] for i in d["items"])); self.assertEqual({i["step"] for i in d["items"]}, {"Definir", "Consultar", "Comprobar"})


if __name__ == "__main__":
    unittest.main()
