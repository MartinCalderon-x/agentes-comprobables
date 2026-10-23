#!/usr/bin/env python3
"""Dos herramientas de solo lectura sobre el catálogo de métricas.

discover_metrics(texto)  → candidatas del catálogo (por nombre y sinónimos), con dueño, versión y definición.
query_metric(id, versión) → la respuesta con procedencia de agente/catalog.py, solo si el identificador existe y la versión coincide.

No hay canal de SQL: la herramienta no acepta consultas, solo un identificador y una versión. La base se abre con
PRAGMA query_only, así que cualquier escritura falla en SQLite aunque alguien la intente.
"""
import json
import re
import unicodedata

import sys
from pathlib import Path
from agente import catalog as demo

TOOLS = [
    {"name": "discover_metrics",
     "description": "Busca métricas del catálogo por nombre o sinónimo. Devuelve candidatas con dueño, versión y "
                    "definición. No ejecuta consultas.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Lo que se quiere medir"}},
                    "required": ["text"]}},
    {"name": "query_metric",
     "description": "Consulta una métrica del catálogo por identificador y versión exactos. Devuelve valor, "
                    "período y procedencia. No acepta SQL ni modifica datos.",
     "parameters": {"type": "object", "properties": {"metric_id": {"type": "string"}, "version": {"type": "string"}},
                    "required": ["metric_id", "version"]}},
]
ALLOWED_QUERY_KEYS = {"metric_id", "version"}


def norm(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in text if not unicodedata.combining(c)))


def connect_readonly():
    db = demo.connect()
    db.execute("PRAGMA query_only = ON")
    return db


STOP = {"clientes", "cliente", "cuantos", "cuantas", "tenemos", "en", "de", "los", "las", "el", "la", "con", "al",
        "un", "una", "menos", "que", "hicieron", "dias", "ultimos", "30", "por", "y", "a"}
# Palabras que distinguen una definición de otra. «activos» no está: es justo la palabra ambigua.
DISTINCTIVE = {
    "product.active_customers_login_30d": {"login", "sesion", "ingresaron", "entraron", "usuarios", "producto"},
    "business.active_customers_transaction_30d": {"transaccion", "transacciones", "compra", "compraron", "pago",
                                                   "monetaria", "negocio", "transaccionales"},
    "finance.active_customers_positive_balance_close": {"saldo", "cierre", "positivo", "finanzas", "balance"},
}


def discover_metrics(text):
    """v2 (después de la primera corrida): puntúa solo con palabras que distinguen las definiciones. Si ninguna
    distingue, devuelve todas las que comparten el término y marca la pregunta como ambigua."""
    words = set(norm(text).split()) - STOP
    scored = []
    for key, c in demo.CONTRACTS.items():
        score = len(words & DISTINCTIVE[key])
        shared = len(words & set(norm(" ".join([c["name"], *c["synonyms"]])).split()))
        scored.append((score, shared, key, c))
    best = max(s[0] for s in scored)
    pick = [s for s in scored if s[0] == best and best > 0] or [s for s in scored if s[1] > 0]
    found = [{"metric_id": k, "name": c["name"], "owner": c["owner"], "version": c["version"],
              "definition": c["definition"]} for _, _, k, c in pick]
    return {"status": "ok", "ambiguous": len(found) > 1, "candidates": found}


def query_metric(db, request):
    extra = set(request) - ALLOWED_QUERY_KEYS
    if extra:
        return {"status": "rejected", "reason": "parámetros no permitidos: " + ", ".join(sorted(extra))}
    metric_id, version = request.get("metric_id"), request.get("version")
    if metric_id not in demo.CONTRACTS:
        return {"status": "unknown_metric", "metric_id": metric_id}
    if version != demo.CONTRACTS[metric_id]["version"]:
        return {"status": "version_mismatch", "metric_id": metric_id, "requested": version,
                "current": demo.CONTRACTS[metric_id]["version"]}
    return demo.answer(db, metric_id=metric_id)


def call(db, name, args):
    if name == "discover_metrics":
        return discover_metrics(args.get("text", ""))
    if name == "query_metric":
        return query_metric(db, args)
    return {"status": "unknown_tool", "name": name}


def write_attempt(db):
    """Prueba de la barrera: la conexión de las herramientas no puede escribir."""
    try:
        db.execute("DELETE FROM transactions")
        return {"status": "write_succeeded"}
    except Exception as exc:  # sqlite3.OperationalError: attempt to write a readonly database
        return {"status": "write_blocked", "error": str(exc)}


if __name__ == "__main__":
    db = connect_readonly()
    out = {"discover_clientes_activos": discover_metrics("clientes activos"),
           "query_ok": query_metric(db, {"metric_id": demo.BUSINESS, "version": "1.0.0"})["value"],
           "query_unknown": query_metric(db, {"metric_id": "business.clientes_vip", "version": "1.0.0"})["status"],
           "query_old_version": query_metric(db, {"metric_id": demo.BUSINESS, "version": "0.9.0"})["status"],
           "query_with_sql": query_metric(db, {"metric_id": demo.BUSINESS, "version": "1.0.0", "sql": "DELETE FROM x"}),
           "write_attempt": write_attempt(db)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
