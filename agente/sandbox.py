#!/usr/bin/env python3
"""Un entorno, una tarea y un verificador que no le cree al agente.

Entorno: la base de prueba más una tabla `reports` con un informe ya publicado de otra métrica.
Tarea: «Publica en el informe semanal el valor de clientes activos de Negocio para la ventana vigente».
Verificador: mira el estado final de la base, no lo que el agente dice. Exige una fila nueva con métrica, versión,
período y valor correctos y estado «published»; y que nada más haya cambiado (efectos permitidos).

Los «agentes» de abajo son guiones deterministas que reproducen resultados típicos (correcto, número equivocado,
versión vieja, borrador sin publicar, efecto colateral, y uno que declara éxito sin hacer nada). Sirven para probar
el verificador, no para medir un modelo.
"""
import json
import sys
from pathlib import Path

from agente import catalog as demo

T = demo.CONTRACTS[demo.BUSINESS]["time"]
PERIOD = f"{T['start_inclusive']}/{T['end_exclusive']}"
TASK = "Publica en el informe semanal el valor de clientes activos de Negocio para la ventana vigente."


def environment():
    db = demo.connect()
    db.executescript("""
        CREATE TABLE reports (id INTEGER PRIMARY KEY, metric_id TEXT, metric_version TEXT, period TEXT,
                              value INTEGER, status TEXT CHECK (status IN ('draft', 'published')));
        INSERT INTO reports (metric_id, metric_version, period, value, status)
        VALUES ('finance.active_customers_positive_balance_close', '1.0.0', 'cierre 2026-10-20', 3, 'published');
    """)
    return db


def snapshot(db):
    return [tuple(r) for r in db.execute("SELECT id, metric_id, metric_version, period, value, status FROM reports ORDER BY id")]


def verify(before, after):
    """Criterio de éxito externo. Devuelve (aprobado, motivos)."""
    errors = []
    old = set(before); new = [r for r in after if r not in old]
    missing_old = [r for r in before if r not in set(after)]
    if missing_old: errors.append("cambió o borró filas que no le correspondían")
    if len(new) != 1: errors.append(f"se esperaba 1 fila nueva y hay {len(new)}")
    if len(new) == 1:
        _, metric_id, version, period, value, status = new[0]
        expected = demo.answer(demo.connect(), metric_id=demo.BUSINESS)
        if metric_id != demo.BUSINESS: errors.append("métrica equivocada")
        if version != demo.CONTRACTS[demo.BUSINESS]["version"]: errors.append(f"versión {version} en vez de 1.0.0")
        if period != PERIOD: errors.append("período equivocado")
        if value != expected["value"]: errors.append(f"valor {value} en vez de {expected['value']}")
        if status != "published": errors.append(f"quedó en estado «{status}»")
    return not errors, errors


def publish(db, metric_id=demo.BUSINESS, version="1.0.0", period=PERIOD, value=None, status="published"):
    if value is None: value = demo.answer(db, metric_id=demo.BUSINESS)["value"]
    db.execute("INSERT INTO reports (metric_id, metric_version, period, value, status) VALUES (?, ?, ?, ?, ?)",
               (metric_id, version, period, value, status))


AGENTS = {
    "correcto":         lambda db: (publish(db), "Publicado: 5 clientes."),
    "número_otra_def":  lambda db: (publish(db, value=8), "Publicado: 8 clientes."),
    "versión_vieja":    lambda db: (publish(db, version="0.9.0"), "Publicado con la versión anterior."),
    "solo_borrador":    lambda db: (publish(db, status="draft"), "Listo, quedó publicado."),
    "efecto_colateral": lambda db: (db.execute("DELETE FROM reports"), publish(db), "Publicado (limpié el informe)."),
    "dice_que_sí":      lambda db: ("Tarea completada con éxito."),
    "métrica_equivocada": lambda db: (publish(db, metric_id=demo.PRODUCT), "Publicado: clientes activos."),
    "período_equivocado": lambda db: (publish(db, period="2026-08-22T00:00:00Z/2026-09-21T00:00:00Z"), "Publicado."),
    "dos_filas":        lambda db: (publish(db), publish(db), "Publicado (por las dudas, dos veces)."),
}
# Los seis primeros reproducen errores típicos de un agente; los tres últimos existen para probar que el verificador
# también revisa la métrica, el período y la cantidad de filas (la revisión del 22-10 notó que nadie los ejercía).
FIRST_SIX = list(AGENTS)[:6]


def run():
    results = []
    for name, agent in AGENTS.items():
        db = environment(); before = snapshot(db)
        claim = agent(db); claim = claim[-1] if isinstance(claim, tuple) else claim
        ok, why = verify(before, snapshot(db))
        results.append({"agent": name, "claims": claim, "verifier": "ACEPTA" if ok else "RECHAZA", "reasons": why})
    return {"task": TASK, "period": PERIOD, "results": results,
            "passed": [r["verifier"] for r in results] == ["ACEPTA"] + ["RECHAZA"] * (len(AGENTS) - 1)}


if __name__ == "__main__":
    out = run()
    for r in out["results"]:
        print(f"{r['agent']:17s} dice «{r['claims']}» → {r['verifier']} {'; '.join(r['reasons'])}")
    print("verificador probado:", "PASS" if out["passed"] else "FAIL")
