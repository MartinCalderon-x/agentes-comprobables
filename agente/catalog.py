#!/usr/bin/env python3
"""Catálogo de métricas: contratos, consultas permitidas sobre SQLite, respuestas con procedencia y verificador.

Determinista y sin modelos. CLI: python3 -m agente.catalog [--json | --metric-id ID | --mutate-lower-bound]
"""
import argparse
import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data"
CATALOG = json.loads((ROOT / "metric_contracts.json").read_text(encoding="utf-8"))
CONTRACTS = {item["metric_id"]: item for item in CATALOG["metrics"]}
GOLDENS = json.loads((ROOT / "golden_questions.json").read_text(encoding="utf-8"))
PRODUCT, BUSINESS, FINANCE = CONTRACTS
QUESTION = "¿Cuántos clientes activos tenemos?"


def connect():
    """Cada ejecución parte de los mismos datos, en memoria y sin red."""
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript((ROOT / "data.sql").read_text(encoding="utf-8"))
    return db


def query_for(metric_id, exclusive_lower=False):
    """Sólo SQL permitido explícitamente. Nunca interpolamos texto del usuario."""
    contract = CONTRACTS[metric_id]
    time = contract["time"]
    lower = ">" if exclusive_lower else ">="  # mutación deliberada para el test
    if metric_id == FINANCE:
        sql = ("SELECT DISTINCT customer_id FROM balances "
               "WHERE snapshot_date = ? AND balance_cents > 0 ORDER BY customer_id")
        params = (time["snapshot_date"],)
    else:
        table = "logins" if metric_id == PRODUCT else "transactions"
        sql = (f"SELECT DISTINCT customer_id FROM {table} "
               f"WHERE occurred_at {lower} ? AND occurred_at < ?")
        if metric_id == BUSINESS:
            sql += " AND status = 'posted' AND amount_cents != 0"
        sql += " ORDER BY customer_id"
        params = (time["start_inclusive"], time["end_exclusive"])
    return sql, params


def members(db, metric_id, exclusive_lower=False):
    sql, params = query_for(metric_id, exclusive_lower)
    return [row[0] for row in db.execute(sql, params)]


def freshness(contract):
    """Comparación contra el reloj fijo del ejercicio, nunca contra hoy."""
    parse = lambda text: datetime.fromisoformat(text.replace("Z", "+00:00"))
    meta = contract["freshness"]
    as_of = parse(CATALOG["evaluation_as_of_utc"])
    current = parse(meta["data_current_through_utc"])
    loaded = parse(meta["loaded_at_utc"])
    age = (as_of - current).total_seconds() / 3600
    return {**meta, "age_hours": age,
            "within_synthetic_sla": 0 <= age <= meta["max_age_hours"]
            and current <= loaded <= as_of}


def answer(db, question=QUESTION, metric_id=None, exclusive_lower=False):
    # No interpreta lenguaje natural. Sin identificador explícito, pide elección.
    if metric_id is None:
        return {"status": "needs_clarification", "question": question,
                "clarification": "¿Producto (login), Negocio (transacción) o "
                "Finanzas (saldo positivo al cierre)?",
                "options": [{"metric_id": key, "name": item["name"]}
                            for key, item in CONTRACTS.items()]}
    if metric_id not in CONTRACTS:
        return {"status": "unknown_metric", "metric_id": metric_id,
                "message": "Métrica desconocida; no se inventa una definición."}
    contract = copy.deepcopy(CONTRACTS[metric_id])
    ids = members(db, metric_id, exclusive_lower)
    sql, params = query_for(metric_id, exclusive_lower)
    return {"status": "ok", "metric_id": metric_id, "value": len(ids),
            "unit": "distinct_customers", "definition": contract["definition"],
            "provenance": {"owner": contract["owner"],
                           "metric_version": contract["version"],
                           "dataset_version": CATALOG["dataset_version"],
                           "evaluation_as_of_utc": CATALOG["evaluation_as_of_utc"],
                           "time": contract["time"],
                           "freshness": freshness(contract),
                           "lineage": contract["lineage"],
                           "executed_sql": sql, "parameters": list(params),
                           "customer_ids": ids}}


def validate_answer(candidate, expected):
    """Oracle pequeño y explícito; no es un juez LLM ni una prueba exhaustiva."""
    errors = []
    for key, value in expected.items():
        if candidate.get(key) != value:
            errors.append(f"{key}: expected={value!r}, actual={candidate.get(key)!r}")
    if expected.get("status") == "ok":
        provenance = candidate.get("provenance", {})
        required = ("owner", "metric_version", "dataset_version", "evaluation_as_of_utc", "time",
                    "freshness", "lineage", "executed_sql", "parameters", "customer_ids")
        for key in required:
            if key not in provenance:
                errors.append(f"missing provenance.{key}")
        metric_id = candidate.get("metric_id")
        if metric_id not in CONTRACTS:
            errors.append("unknown canonical metric_id")
        else:
            contract = CONTRACTS[metric_id]
            for key, value in {"definition": contract["definition"],
                               "unit": "distinct_customers"}.items():
                if candidate.get(key) != value:
                    errors.append(f"{key} differs from canonical contract")
            sql, params = query_for(metric_id)
            canonical = {"owner": contract["owner"], "metric_version": contract["version"],
                         "dataset_version": CATALOG["dataset_version"],
                         "evaluation_as_of_utc": CATALOG["evaluation_as_of_utc"],
                         "time": contract["time"], "lineage": contract["lineage"],
                         "freshness": freshness(contract),
                         "executed_sql": sql, "parameters": list(params)}
            for key, value in canonical.items():
                if provenance.get(key) != value:
                    errors.append(f"provenance.{key} differs from canonical contract")
        ids = provenance.get("customer_ids", [])
        if len(ids) != len(set(ids)) or len(ids) != candidate.get("value"):
            errors.append("value/customer_ids mismatch or duplicate customers")
    return errors


def evaluate_goldens(db, exclusive_lower=False):
    results = []
    for case in GOLDENS:
        if "expected" in case:
            expected = dict(case["expected"])
            if expected["status"] == "ok":
                expected["metric_id"] = case["metric_id"]
            actual = answer(db, case["question"], case.get("metric_id"), exclusive_lower)
            errors = validate_answer(actual, expected)
        else:
            ids = members(db, case["metric_id"], exclusive_lower)
            expected, actual = case["expected_occurrences"], ids.count(case["customer_id"])
            errors = [] if expected == actual else [f"expected={expected}, actual={actual}"]
        results.append({"id": case["id"], "passed": not errors, "errors": errors})
    return results


def build_report(db, exclusive_lower=False):
    answers = [answer(db, metric_id=key, exclusive_lower=exclusive_lower)
               for key in CONTRACTS]
    wrong = copy.deepcopy(answer(db, metric_id=BUSINESS))
    wrong["value"] = 8  # respuesta plausible, pero incorrecta para Negocio
    wrong_errors = validate_answer(wrong, {"status": "ok", "metric_id": BUSINESS, "value": 5})
    checks = evaluate_goldens(db, exclusive_lower)
    return {"mode": "deterministic_sqlite_harness_no_llm",
            "mutated_lower_boundary": exclusive_lower,
            "counts": {item["metric_id"]: item["value"] for item in answers},
            "ambiguous_answer": answer(db), "canonical_answers": answers,
            "golden_checks": checks,
            "deliberately_wrong_answer": {"metric_id": BUSINESS, "value": 8,
                                          "rejected": bool(wrong_errors), "errors": wrong_errors},
            "passed": all(item["passed"] for item in checks) and bool(wrong_errors)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Informe completo JSON")
    parser.add_argument("--metric-id", help="Responder con este identificador explícito")
    parser.add_argument("--mutate-lower-bound", action="store_true",
                        help="Prueba negativa: cambia >= por >; debe fallar con salida 1")
    args = parser.parse_args(argv)
    db = connect()
    try:
        if args.metric_id:
            result = answer(db, metric_id=args.metric_id, exclusive_lower=args.mutate_lower_bound)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ok" else 2
        report = build_report(db, args.mutate_lower_bound)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Clientes activos | Contratos y verificación")
            if args.mutate_lower_bound:
                print("MUTACIÓN INTENCIONAL: la consulta usa > en vez de >=; viola el contrato.")
            for label, key in zip(("Producto", "Negocio", "Finanzas"), CONTRACTS):
                print(f"{label}: {report['counts'][key]}")
            ambiguous = report["ambiguous_answer"]
            print(f"Pregunta: {QUESTION}")
            print(f"Estado: {ambiguous['status']}. {ambiguous['clarification']}")
            explicit = report["canonical_answers"][1]
            print(f"Respuesta explícita: {explicit['metric_id']} = {explicit['value']}")
            print("Proveniencia: versión 1.0.0; data.sql -> transactions; clientes distintos;")
            print("  Contrato UTC [2026-09-21T00:00:00Z, 2026-10-21T00:00:00Z); posted; amount_cents != 0.")
            print("  Frescura al corte de evaluación: 2 h; objetivo: 24 h.")
            passed = sum(item["passed"] for item in report["golden_checks"])
            print(f"Casos golden: {passed}/{len(GOLDENS)} correctos.")
            print("Respuesta errónea deliberada (Negocio=8): RECHAZADA.")
            for check in report["golden_checks"]:
                if not check["passed"]:
                    print(f"FAIL {check['id']}: {'; '.join(check['errors'])}")
            print("RESULTADO: " + ("PASS" if report["passed"] else "FAIL"))
        return 0 if report["passed"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
