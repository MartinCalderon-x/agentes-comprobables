#!/usr/bin/env python3
"""Una definición, dos consumidores: tablero y agente sobre el mismo contrato.

Una tarjeta de tablero y la respuesta de un agente leen el mismo contrato (demo.answer). La prueba de paridad exige
que coincidan en identificador, versión, período, filtros y valor. Para mostrar qué se evita, hay también un tablero
«copiado»: la misma métrica reescrita a mano en su propio SQL, con un detalle distinto (cuenta las transacciones
pendientes). Una versión que el catálogo no conoce falla de forma explícita.
"""
import json
import sys
from pathlib import Path

from agente import catalog as demo

KEYS = ("metric_id", "metric_version", "period", "filter", "value")


def from_contract(db, metric_id, version):
    if metric_id not in demo.CONTRACTS:
        return {"status": "unknown_metric", "metric_id": metric_id}
    c = demo.CONTRACTS[metric_id]
    if version != c["version"]:
        return {"status": "unknown_version", "metric_id": metric_id, "requested": version, "current": c["version"]}
    a = demo.answer(db, metric_id=metric_id)
    t = c["time"]
    period = f"{t['start_inclusive']} → {t['end_exclusive']}" if "start_inclusive" in t else f"cierre {t['snapshot_date']}"
    return {"status": "ok", "metric_id": metric_id, "metric_version": c["version"], "period": period,
            "filter": c["lineage"]["filter"], "value": a["value"]}


def dashboard_card(db, metric_id, version):
    """Consumidor 1: la tarjeta del tablero."""
    return {"consumer": "tablero", **from_contract(db, metric_id, version)}


def agent_answer(db, metric_id, version):
    """Consumidor 2: la respuesta del agente (la misma llamada que query_metric)."""
    return {"consumer": "agente", **from_contract(db, metric_id, version)}


def copied_dashboard(db):
    """Antiejemplo: la regla copiada en el tablero, con su propio SQL. Olvida excluir las pendientes."""
    t = demo.CONTRACTS[demo.BUSINESS]["time"]
    rows = db.execute("SELECT DISTINCT customer_id FROM transactions WHERE occurred_at >= ? AND occurred_at < ? "
                      "AND status IN ('posted', 'pending') AND amount_cents != 0",
                      (t["start_inclusive"], t["end_exclusive"])).fetchall()
    return {"consumer": "tablero copiado", "status": "ok", "metric_id": demo.BUSINESS, "metric_version": "1.0.0",
            "period": f"{t['start_inclusive']} → {t['end_exclusive']}",
            "filter": "start <= occurred_at < end AND status IN ('posted','pending') AND amount_cents != 0",
            "value": len(rows)}


def parity(a, b):
    diffs = [k for k in KEYS if a.get(k) != b.get(k)]
    return {"passed": not diffs and a.get("status") == b.get("status") == "ok", "differences": diffs}


def report(db):
    card = dashboard_card(db, demo.BUSINESS, "1.0.0")
    agent = agent_answer(db, demo.BUSINESS, "1.0.0")
    copy = copied_dashboard(db)
    unknown = dashboard_card(db, demo.BUSINESS, "2.0.0")
    return {"card": card, "agent": agent, "parity_shared_contract": parity(card, agent),
            "copied_card": copy, "parity_copied_rule": parity(copy, agent),
            "unknown_version": unknown}


if __name__ == "__main__":
    print(json.dumps(report(demo.connect()), ensure_ascii=False, indent=2))
