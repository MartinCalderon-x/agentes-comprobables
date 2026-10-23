#!/usr/bin/env python3
"""Cuánto contexto necesita el agente: dos formas de resolver las mismas preguntas, medidas.

A · contexto extenso: el agente recibe en el prompt toda la documentación del laboratorio (README, catálogo completo
    y el SQL con el esquema y los datos) y una sola herramienta, query_metric.
B · descubrimiento selectivo: el agente no recibe nada de eso; tiene discover_metrics y query_metric (agente/tools.py).

Mismo modelo, misma temperatura (0), mismas ocho preguntas, tres repeticiones por pregunta y por modo. Se guardan
todas las corridas: tokens de entrada y salida que informa el proveedor, latencia de punta a punta, cantidad de
llamadas a herramientas y si la respuesta pasa la regla de su pregunta. No hay ahorro supuesto: lo que sale es lo
que se publica, también si es desfavorable.
"""
import json
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RESULTS = REPO / "evals" / "results"
from agente import catalog as demo
from agente import tools as T
from agente import llm as G

SYSTEM = ("Eres un agente de datos. Respondes preguntas sobre clientes. Si hay más de una métrica posible para la "
          "pregunta, no elijas: pregunta cuál necesita la persona. Para dar un número, llama a query_metric con el "
          "identificador y la versión exactos del catálogo. Nunca inventes números ni definiciones. Responde en "
          "español, en una o dos frases.")
SYSTEM_B = SYSTEM + " Para saber qué métricas existen, usa discover_metrics."
CONTEXT_A = ("Documentación completa del sistema de datos. Úsala para elegir la métrica.\n\n"
             + (REPO / "docs" / "catalogo.md").read_text(encoding="utf-8") + "\n\n## metric_contracts.json\n"
             + (REPO / "data" / "metric_contracts.json").read_text(encoding="utf-8") + "\n\n## data.sql\n"
             + (REPO / "data" / "data.sql").read_text(encoding="utf-8"))
CASES = [
    {"id": "login", "q": "¿Cuántos clientes iniciaron sesión en los últimos 30 días?", "metric": demo.PRODUCT, "value": 8},
    {"id": "entraron", "q": "¿Cuántos usuarios entraron a la app en los últimos 30 días?", "metric": demo.PRODUCT, "value": 8},
    {"id": "transaccion", "q": "¿Cuántos clientes hicieron al menos una transacción en los últimos 30 días?", "metric": demo.BUSINESS, "value": 5},
    {"id": "compraron", "q": "¿Cuántos clientes compraron algo en los últimos 30 días?", "metric": demo.BUSINESS, "value": 5},
    {"id": "saldo", "q": "¿Cuántos clientes terminaron con saldo positivo al cierre?", "metric": demo.FINANCE, "value": 3},
    {"id": "saldo_corto", "q": "¿Cuántos clientes tienen saldo?", "metric": demo.FINANCE, "value": 3},
    {"id": "ambigua", "q": "¿Cuántos clientes activos tenemos?"},
    {"id": "vip", "q": "¿Cuántos clientes VIP tenemos?"},
]
REPEATS = 3
NUM = re.compile(r"\b(\d+)\b")


def numbers(text):
    """Números de la respuesta, sin los que vienen del período (30 días, 2026, 20 y 21 de octubre)."""
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text)          # versiones (1.0.0) no son cantidades
    text = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", text)             # separador de miles: 1.000 → 1000
    return {int(n) for n in NUM.findall(text) if int(n) not in (30, 2026, 20, 21)}


def grade(case, run):
    """v2 de la regla (después de la primera corrida): pedir aclaración cuenta aunque no termine en «?», y un número
    inventado se detecta aunque sea grande (la v1 descartaba los mayores a 999 y no veía un «1000»)."""
    if run.get("error"): return False, "error"
    final = run.get("final") or ""; queried = [t for t in run["trace"] if t["tool"] == "query_metric" and t["status"] == "ok"]
    nums = numbers(final)
    if "metric" in case:
        if any(t["args"].get("metric_id") == case["metric"] for t in queried) and case["value"] in nums:
            return True, "métrica y número correctos"
        if nums and not queried: return False, "inventó un número sin consultar"
        if not queried: return False, "no consultó (pidió aclarar o explicó)"
        return False, "consultó otra métrica"
    clarifies = "?" in final or re.search(r"aclar|cuál|a qué te refieres", final.lower())
    if case["id"] == "ambigua":
        return (not queried and not nums and bool(clarifies)), "pidió aclarar" if not queried else "eligió sin preguntar"
    return (not queried and not nums), "no inventó" if not nums else "inventó un número"


def run_mode(db, mode):
    runs = []
    for case in CASES:
        for rep in range(REPEATS):
            if mode == "A":
                r = G.run_agent(case["q"], SYSTEM, [T.TOOLS[1]], lambda n, a: T.call(db, n, a), context=CONTEXT_A)
            else:
                r = G.run_agent(case["q"], SYSTEM_B, T.TOOLS, lambda n, a: T.call(db, n, a))
            ok, why = grade(case, r)
            runs.append({"mode": mode, "case": case["id"], "rep": rep + 1, "passed": ok, "why": why, **r})
            print(f"{mode} {case['id']:12s} #{rep + 1} {'OK ' if ok else 'MAL'} in={r.get('usage', {}).get('prompt')} "
                  f"out={r.get('usage', {}).get('output')} {r.get('latency_ms')} ms {[t['tool'] for t in r['trace']]}")
    return runs


def summary(runs):
    ok = [r for r in runs if not r.get("error")]
    med = lambda xs: round(statistics.median(xs)) if xs else None
    return {"runs": len(runs), "errors": len(runs) - len(ok), "passed": sum(r["passed"] for r in runs),
            "prompt_tokens_median": med([r["usage"]["prompt"] for r in ok]),
            "output_tokens_median": med([r["usage"]["output"] for r in ok]),
            "prompt_tokens_total": sum(r["usage"]["prompt"] for r in ok),
            "latency_ms_median": med([r["latency_ms"] for r in ok]),
            "tool_calls_median": med([len(r["trace"]) for r in ok]),
            "failed_cases": sorted({r["case"] for r in runs if not r["passed"]}),
            "invented_numbers": sum(r.get("why") == "inventó un número sin consultar" for r in runs)}


def regrade(path):
    """Recalifica corridas guardadas con la regla vigente, sin volver a llamar al modelo."""
    out = json.loads(Path(path).read_text(encoding="utf-8")); cases = {c["id"]: c for c in CASES}
    for r in out["runs"]:
        r["passed"], r["why"] = grade(cases[r["case"]], r)
    out["summary"] = {m: summary([r for r in out["runs"] if r["mode"] == m]) for m in ("A", "B")}
    out["grader"] = "v2"
    Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main():
    if "--recalificar" in sys.argv:
        print(json.dumps(regrade(RESULTS / "contexto_openrouter.json")["summary"], ensure_ascii=False, indent=1)); return
    db = T.connect_readonly()
    out = {"model": G.pick_model(), "temperature": 0.0, "repeats": REPEATS, "cases": CASES,
           "context_A_chars": len(CONTEXT_A), "runs": []}
    for mode in ("A", "B"):
        out["runs"] += run_mode(db, mode)
    out["model_reported"] = next((r.get("model") for r in out["runs"] if r.get("model")), None)
    out["summary"] = {m: summary([r for r in out["runs"] if r["mode"] == m]) for m in ("A", "B")}
    name = "contexto_lmstudio.json" if G.LOCAL else "contexto_openrouter.json"
    out["grader"] = "v2"
    (RESULTS / name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
