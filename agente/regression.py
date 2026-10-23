#!/usr/bin/env python3
"""Suite de regresión con política de bloqueo y alerta.

Junta las pruebas del catálogo, la paridad y el verificador, y clasifica cada falla:
- BLOQUEA: el valor o la consulta cambian sin que cambie la versión del contrato (regresión).
- ALERTA: los datos llegaron tarde (frescura fuera del objetivo). No es un error de la lógica: avisa y no bloquea.
- PASA: todo coincide. Un cambio intencional se reconoce porque sube la versión y actualiza los esperados.

Uso:  python3 -m agente.regression [--escenario normal|borde_roto|datos_tarde|restaurado] [--json]
Sale con 1 si hay algo que bloquea; con 0 si pasa o solo hay alertas (así la usa la CI de .github/workflows/ci.yml).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from agente import catalog as demo
from agente import consumers as E3
from agente import sandbox as E5


def freshness_age_hours(as_of):
    parse = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))
    cur = parse(demo.CONTRACTS[demo.BUSINESS]["freshness"]["data_current_through_utc"])
    return (as_of - cur).total_seconds() / 3600


def suite(escenario="normal"):
    db = demo.connect()
    mutate = escenario == "borde_roto"
    checks = []
    goldens = demo.evaluate_goldens(db, exclusive_lower=mutate)
    failed = [g["id"] for g in goldens if not g["passed"]]
    checks.append({"check": "preguntas de referencia", "total": len(goldens), "failed": failed,
                   "level": "BLOQUEA" if failed else "PASA"})
    # Tablero y agente leen la misma consulta del contrato (agente/consumers.py): si se rompe, cambian los dos juntos y la
    # paridad no lo ve. Lo que lo atrapa son las preguntas de referencia, que tienen el valor esperado escrito aparte.
    value = len(demo.members(db, demo.BUSINESS, exclusive_lower=mutate))
    card = dict(E3.dashboard_card(db, demo.BUSINESS, "1.0.0"), value=value)
    agent = dict(E3.agent_answer(db, demo.BUSINESS, "1.0.0"), value=value)
    par = E3.parity(card, agent)
    checks.append({"check": "paridad tablero/agente", "differences": par["differences"], "value": value,
                   "level": "PASA" if par["passed"] else "BLOQUEA"})
    ver = E5.run()
    checks.append({"check": "verificador de la tarea", "level": "PASA" if ver["passed"] else "BLOQUEA"})
    as_of = datetime.fromisoformat(demo.CATALOG["evaluation_as_of_utc"].replace("Z", "+00:00"))
    if escenario == "datos_tarde": as_of += timedelta(hours=30)
    age = freshness_age_hours(as_of); sla = demo.CONTRACTS[demo.BUSINESS]["freshness"]["max_age_hours"]
    checks.append({"check": "frescura de los datos", "age_hours": age, "objective_hours": sla,
                   "level": "PASA" if age <= sla else "ALERTA"})
    levels = [c["level"] for c in checks]
    result = "BLOQUEA" if "BLOQUEA" in levels else ("ALERTA" if "ALERTA" in levels else "PASA")
    counts = {k: len(demo.members(db, k, exclusive_lower=mutate)) for k in demo.CONTRACTS}
    return {"escenario": escenario, "checks": checks, "result": result, "counts": counts}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--escenario", default="normal", choices=["normal", "borde_roto", "datos_tarde", "restaurado"])
    p.add_argument("--json", action="store_true"); a = p.parse_args(argv)
    out = suite(a.escenario)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for c in out["checks"]:
            extra = c.get("failed") or c.get("differences") or (f"{c['age_hours']:.0f} h / {c['objective_hours']} h" if "age_hours" in c else "")
            print(f"{c['level']:8s} {c['check']} {extra if extra else ''}")
        print(f"RESULTADO ({a.escenario}): {out['result']}")
    return 1 if out["result"] == "BLOQUEA" else 0


if __name__ == "__main__":
    raise SystemExit(main())
