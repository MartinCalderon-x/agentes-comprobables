"""Validación del proceso completo, agrupada en sus tres pasos: definir, consultar y comprobar.

Cada chequeo corre en vivo sobre la base de prueba (sin modelo) y dice con qué comando se reproduce por separado.
Las evaluaciones con modelo no se corren acá porque tardan: se muestran sus resultados guardados en evals/results.

Uso: python3 -m agente.validacion   (sale con 1 si algún chequeo falla)
"""
import json
import sys
from pathlib import Path

from agente import catalog as demo
from agente import chat
from agente import consumers as E3
from agente import regression as E6
from agente import sandbox as E5
from agente import tools as T

RESULTS = Path(__file__).resolve().parents[1] / "evals" / "results"


def item(step, name, passed, detail, command):
    return {"step": step, "name": name, "passed": bool(passed), "detail": detail, "command": command}


def run():
    db = demo.connect(); ro = T.connect_readonly(); out = []
    counts = {k: demo.answer(db, metric_id=k)["value"] for k in demo.CONTRACTS}
    out.append(item("Definir", "Tres definiciones de «cliente activo»", list(counts.values()) == [8, 5, 3],
                    f"Producto {counts[demo.PRODUCT]} · Negocio {counts[demo.BUSINESS]} · Finanzas {counts[demo.FINANCE]}",
                    "python3 -m agente.catalog"))
    amb = demo.answer(db)
    out.append(item("Definir", "La pregunta ambigua pide aclarar", amb["status"] == "needs_clarification",
                    amb.get("clarification", ""), "python3 -m agente.catalog --json"))
    gold = demo.evaluate_goldens(db); ok = sum(g["passed"] for g in gold)
    out.append(item("Definir", "Casos de referencia", ok == len(gold), f"{ok} de {len(gold)} correctos", "python3 -m agente.catalog"))

    rej = [("Métrica inexistente", T.query_metric(ro, {"metric_id": "business.clientes_vip", "version": "1.0.0"})["status"], "unknown_metric"),
           ("Versión que no es la vigente", T.query_metric(ro, {"metric_id": demo.BUSINESS, "version": "0.9.0"})["status"], "version_mismatch"),
           ("Pedido con SQL", T.query_metric(ro, {"metric_id": demo.BUSINESS, "version": "1.0.0", "sql": "DELETE"})["status"], "rejected"),
           ("Escritura en la base", T.write_attempt(ro)["status"], "write_blocked")]
    for name, got, want in rej:
        out.append(item("Consultar", f"Rechaza: {name.lower()}", got == want, got, "python3 -m agente.tools"))
    p = E3.report(demo.connect())
    out.append(item("Consultar", "Tablero y agente leen el mismo contrato", p["parity_shared_contract"]["passed"],
                    f"tablero {p['card']['value']} · agente {p['agent']['value']}", "python3 -m agente.consumers"))
    out.append(item("Consultar", "La paridad detecta una regla copiada", not p["parity_copied_rule"]["passed"],
                    f"copia {p['copied_card']['value']} contra {p['agent']['value']}: difiere en {', '.join(p['parity_copied_rule']['differences'])}",
                    "python3 -m agente.consumers"))

    wrong = dict(demo.answer(db, metric_id=demo.BUSINESS), value=8)
    errs = demo.validate_answer(wrong, {"status": "ok", "metric_id": demo.BUSINESS, "value": 5})
    out.append(item("Comprobar", "El verificador rechaza «Negocio = 8»", bool(errs), errs[0] if errs else "aceptada", "python3 -m agente.catalog"))
    inv = chat.check_evidence("El número de clientes con saldo positivo al cierre es 1000.",
                              [{"tool": "discover_metrics", "status": "ok", "value": None}])
    out.append(item("Comprobar", "Un número sin consulta se marca", not inv["passed"], inv["detail"], "tests/test_chat.py"))
    sb = E5.run(); acc = [r["agent"] for r in sb["results"] if r["verifier"] == "ACEPTA"]
    out.append(item("Comprobar", "El verificador de la tarea no le cree al agente", sb["passed"] and acc == ["correcto"],
                    f"acepta {len(acc)} de {len(sb['results'])} casos; rechaza los {len(sb['results']) - len(acc)} incorrectos",
                    "python3 -m agente.sandbox"))
    scen = {e: E6.suite(e)["result"] for e in ("normal", "borde_roto", "restaurado", "datos_tarde")}
    out.append(item("Comprobar", "La suite de regresión clasifica cada falla",
                    scen == {"normal": "PASA", "borde_roto": "BLOQUEA", "restaurado": "PASA", "datos_tarde": "ALERTA"},
                    " · ".join(f"{k.replace('_', ' ')}: {v.lower()}" for k, v in scen.items()),
                    "python3 -m agente.regression --escenario borde_roto"))
    db.close(); ro.close()
    return out


def saved_evals():
    """Resumen de las corridas con modelo guardadas (no se vuelven a correr acá)."""
    rows = []
    h = RESULTS / "herramientas.json"
    if h.exists():
        d = json.loads(h.read_text(encoding="utf-8")); s = d["summary"]
        rows.append({"name": "Herramientas con un modelo", "model": d.get("model_version") or d.get("model"),
                     "detail": f"{sum(v == d['repeats'] for v in s.values())} de {len(s)} preguntas", "command": "python3 evals/tools_eval.py"})
    for f, where in (("contexto_lmstudio.json", "LM Studio, local"), ("contexto_openrouter.json", "remoto")):
        p = RESULTS / f
        if not p.exists(): continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for m, label in (("A", "todo en el prompt"), ("B", "búsqueda selectiva")):
            rs = [r for r in d["runs"] if r["mode"] == m]; cases = {}
            for r in rs: cases.setdefault(r["case"], []).append(r["passed"])
            inv = len({r["case"] for r in rs if r.get("why") == "inventó un número sin consultar"})
            rows.append({"name": f"Contexto · {label}", "model": f"{d.get('model_reported') or d.get('model')} ({where})",
                         "detail": f"{sum(all(v) for v in cases.values())} de {len(cases)} preguntas · {inv} con número inventado",
                         "command": "python3 evals/context_eval.py"})
    return rows


def main():
    items = run()
    for it in items:
        print(f"{'OK ' if it['passed'] else 'MAL'} [{it['step']}] {it['name']}: {it['detail']}")
    bad = [i for i in items if not i["passed"]]
    print(f"\n{len(items) - len(bad)} de {len(items)} chequeos pasan")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
