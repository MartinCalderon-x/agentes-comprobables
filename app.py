#!/usr/bin/env python3
"""Agentes comprobables · tablero, chat y validación del proceso en el navegador.

    python3 app.py                 abre http://127.0.0.1:8000
    python3 app.py --port 8080     otro puerto
    python3 app.py --no-browser    sin abrir el navegador

Solo biblioteca estándar. Escucha únicamente en 127.0.0.1. El chat usa un modelo local de LM Studio si está
encendido (ver agente/llm.py); si no, responde sin modelo con el mismo proceso.
"""
import argparse
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from agente import catalog as demo
from agente import chat
from agente import consumers as E3
from agente import llm
from agente import validacion

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "web" / "index.html"
AREA = {demo.PRODUCT: "Producto", demo.BUSINESS: "Negocio", demo.FINANCE: "Finanzas"}
SHORT = {demo.PRODUCT: "Iniciaron sesión al menos una vez en la ventana.",
         demo.BUSINESS: "Al menos una transacción contabilizada, de importe distinto de cero, en la ventana.",
         demo.FINANCE: "Saldo positivo en el cierre. Es un saldo, no actividad."}
MAX_BODY = 64 * 1024


def tablero():
    db = demo.connect()
    cards = []
    for key, c in demo.CONTRACTS.items():
        a = demo.answer(db, metric_id=key); p = a["provenance"]; t = p["time"]
        period = (f"{t['start_inclusive'][:10]} → {t['end_exclusive'][:10]} (fin excluido)" if "start_inclusive" in t
                  else f"Cierre del {t['snapshot_date']}")
        cards.append({"metric_id": key, "area": AREA[key], "name": c["name"], "value": a["value"],
                      "definition": c["definition"], "short": SHORT[key], "owner": c["owner"], "version": c["version"], "period": period,
                      "timezone": t["timezone"], "freshness_hours": p["freshness"]["age_hours"],
                      "freshness_max": p["freshness"]["max_age_hours"], "fresh": p["freshness"]["within_synthetic_sla"],
                      "source": f"{p['lineage']['file']} → {p['lineage']['table']}", "filter": p["lineage"]["filter"],
                      "sql": p["executed_sql"], "parameters": p["parameters"], "customer_ids": p["customer_ids"]})
    rep = E3.report(db)
    db.close()
    return {"cards": cards, "dataset": demo.CATALOG["dataset_version"], "as_of": demo.CATALOG["evaluation_as_of_utc"],
            "parity": {"passed": rep["parity_shared_contract"]["passed"], "card": rep["card"]["value"], "agent": rep["agent"]["value"]}}


class Handler(BaseHTTPRequestHandler):
    server_version = "agentes-comprobables"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/estado":
                return self._send(200, {"model": llm.status(), "dataset": demo.CATALOG["dataset_version"]})
            if path == "/api/tablero":
                return self._send(200, tablero())
            if path == "/api/validar":
                return self._send(200, {"items": validacion.run(), "evals": validacion.saved_evals()})
            self._send(404, {"error": "no existe"})
        except Exception as e:  # el error se muestra en la pantalla, no tumba el servidor
            self._send(500, {"error": str(e)})

    def do_POST(self):
        try:
            if urlsplit(self.path).path != "/api/chat":
                return self._send(404, {"error": "no existe"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY: return self._send(413, {"error": "pedido demasiado grande"})
            body = json.loads(self.rfile.read(n) or b"{}")
            q = str(body.get("question", "")).strip()[:500]
            mid = body.get("metric_id")
            if mid is not None and mid not in demo.CONTRACTS: return self._send(400, {"error": "métrica desconocida"})
            if not q and not mid: return self._send(400, {"error": "falta la pregunta"})
            mode = body.get("mode") if body.get("mode") in ("modelo", "sin_modelo") else None
            hist = [h for h in body.get("history", [])[-6:] if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)]
            self._send(200, chat.answer(q or "¿Cuántos clientes activos tenemos?", metric_id=mid, history=hist, mode=mode))
        except Exception as e:
            self._send(500, {"error": str(e)})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    httpd = None
    for port in range(a.port, a.port + 20):           # si el puerto está ocupado, prueba el siguiente
        try: httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler); break
        except OSError: continue
    if not httpd: sys.exit(f"No hay puertos libres entre {a.port} y {a.port + 19}")
    url = f"http://127.0.0.1:{httpd.server_port}"
    st = llm.status()
    print(f"\n  Agentes comprobables → {url}")
    print(f"  Chat: {'modelo ' + st['model'] + (' (LM Studio, local)' if st['local'] else '') if st['available'] else 'sin modelo · ' + st['reason']}")
    print("  Ctrl+C para salir\n")
    if not a.no_browser: threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\n  Listo.")
    finally: httpd.server_close()


if __name__ == "__main__":
    main()
