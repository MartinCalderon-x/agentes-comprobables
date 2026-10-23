"""Agente de chat sobre el catálogo: responde preguntas de negocio con evidencia.

Proceso en tres pasos, el mismo con o sin modelo:
  1. Definir: la pregunta se resuelve contra el catálogo de métricas (discover_metrics). Si hay más de una
     definición posible, el agente pregunta cuál; no elige en silencio.
  2. Consultar: la métrica se consulta por identificador y versión (query_metric), en una conexión de solo lectura.
  3. Comprobar: antes de devolver la respuesta, se verifica que cada número del texto venga de una consulta de la
     traza. Un número sin traza se marca.

Modos:
  "modelo"     un modelo local en LM Studio (o el servidor de AGENTE_BASE_URL) decide qué herramientas usar.
  "sin_modelo" reglas fijas sobre el mismo catálogo: búsqueda por palabras, sin interpretar lenguaje natural.
"""
import re
import unicodedata

from agente import catalog as demo
from agente import llm
from agente import tools as T

SYSTEM = ("Eres un agente de datos. Respondes preguntas sobre clientes usando solo las herramientas. "
          "Primero descubre la métrica con discover_metrics. Si hay más de una métrica posible para la pregunta, "
          "no elijas: pregunta cuál necesita la persona y nombra las opciones. Para dar un número, llama a "
          "query_metric con el identificador y la versión exactos que devolvió el catálogo. Nunca inventes números "
          "ni definiciones. Solo puedes consultar: no puedes crear, modificar ni borrar datos. "
          "Responde en español, en una o dos frases, y menciona el período de la métrica.")
WRITE = re.compile(r"\b(borr|elimin|actualiz|modific|insert|cre[aá]|agreg|delete|update|drop)\w*", re.I)
NUM = re.compile(r"\b(\d+)\b")
LABEL = {demo.PRODUCT: "Producto", demo.BUSINESS: "Negocio", demo.FINANCE: "Finanzas"}


def numbers(text):
    """Cantidades del texto. No cuenta versiones (1.0.0), años, ni los días y períodos del catálogo."""
    text = re.sub(r"\b\d+\.\d+\.\d+\b", " ", text or "")
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}(T[\d:]+Z?)?\b", " ", text)
    text = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", text)
    return {int(n) for n in NUM.findall(text) if int(n) not in (30, 2026, 20, 21)}


def check_evidence(final, trace):
    """Paso 3: cada número de la respuesta tiene que haber salido de una consulta ok de la traza."""
    returned = {t["value"] for t in trace if t["tool"] == "query_metric" and t.get("status") == "ok"}
    nums = numbers(final)
    orphan = sorted(n for n in nums if n not in returned)
    if orphan:
        return {"passed": False, "label": "Número sin traza", "detail": f"{', '.join(map(str, orphan))} no viene de ninguna consulta"}
    if nums:
        return {"passed": True, "label": "Número con traza", "detail": "cada número viene de query_metric"}
    return {"passed": True, "label": "Sin números", "detail": "la respuesta no afirma cantidades"}


def evidence_from(trace):
    """La procedencia de la última consulta ok, para mostrarla junto a la respuesta."""
    for t in reversed(trace):
        if t["tool"] == "query_metric" and t.get("status") == "ok" and t.get("result"):
            r = t["result"]; p = r["provenance"]; time = p["time"]
            period = (f"{time['start_inclusive'][:10]} → {time['end_exclusive'][:10]} (fin excluido), UTC"
                      if "start_inclusive" in time else f"cierre del {time['snapshot_date']}, UTC")
            return {"metric_id": r["metric_id"], "area": LABEL.get(r["metric_id"]), "value": r["value"],
                    "definition": r["definition"], "owner": p["owner"], "version": p["metric_version"],
                    "period": period, "source": f"{p['lineage']['file']} → {p['lineage']['table']}",
                    "sql": p["executed_sql"], "parameters": p["parameters"], "customer_ids": p["customer_ids"]}
    return None


def _call(db, trace, name, args):
    result = T.call(db, name, args)
    trace.append({"tool": name, "args": args, "status": result.get("status"), "value": result.get("value"), "result": result})
    return result


def _norm(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def answer_without_model(db, question, metric_id=None):
    """Las mismas tres etapas con reglas fijas. Con metric_id (la persona eligió una opción) salta la búsqueda."""
    trace = []
    if WRITE.search(_norm(question)) and not metric_id:
        return {"final": "Solo puedo consultar métricas: no tengo permisos para crear, modificar ni borrar datos.", "trace": trace}
    if not metric_id:
        found = _call(db, trace, "discover_metrics", {"text": question})
        cands = found["candidates"]
        if not cands:
            names = "; ".join(c["name"] for c in demo.CONTRACTS.values())
            return {"final": f"No encuentro una métrica para eso en el catálogo. Las que existen son: {names}.", "trace": trace}
        if len(cands) > 1:
            return {"final": "Hay más de una definición posible. ¿Cuál necesitas?", "trace": trace,
                    "options": [{"metric_id": c["metric_id"], "label": f"{c['owner']}: {c['name']}"} for c in cands]}
        metric_id = cands[0]["metric_id"]
    r = _call(db, trace, "query_metric", {"metric_id": metric_id, "version": demo.CONTRACTS[metric_id]["version"]})
    if r.get("status") != "ok":
        return {"final": "No pude consultar esa métrica.", "trace": trace}
    c = demo.CONTRACTS[metric_id]
    when = "en los últimos 30 días" if "start_inclusive" in c["time"] else f"al cierre del {c['time']['snapshot_date']}"
    what = {demo.PRODUCT: "iniciaron sesión", demo.BUSINESS: "tuvieron al menos una transacción contabilizada",
            demo.FINANCE: "tenían saldo positivo"}[metric_id]
    return {"final": f"{r['value']} clientes {what} {when} ({LABEL[metric_id]}, versión {c['version']}).", "trace": trace}


def answer(question, metric_id=None, history=None, mode=None):
    """Punto de entrada del chat. Devuelve texto, traza, evidencia, chequeo y el modo que respondió."""
    db = T.connect_readonly()
    try:
        st = llm.status() if mode != "sin_modelo" else {"available": False}
        use_model = mode == "modelo" or (mode is None and st.get("available"))
        if use_model and not metric_id:
            r = llm.run_agent(question, SYSTEM, T.TOOLS, lambda n, a: T.call(db, n, a), history=history)
            if r.get("error"):
                out = answer_without_model(db, question, metric_id)
                out["note"] = f"El modelo no respondió ({r['error'][:120]}); contesté sin modelo."
                out["mode"] = "sin_modelo"
            else:
                out = {"final": r["final"], "trace": r["trace"], "mode": "modelo", "model": r.get("model") or st.get("model"),
                       "latency_ms": r.get("latency_ms"), "usage": r.get("usage")}
                # Si el modelo pidió aclarar, las opciones del catálogo quedan como botones (no se elige en silencio)
                queried = any(t["tool"] == "query_metric" and t.get("status") == "ok" for t in r["trace"])
                found = [t["result"] for t in r["trace"] if t["tool"] == "discover_metrics" and t.get("result")]
                if not queried and found and found[-1].get("ambiguous"):
                    out["options"] = [{"metric_id": c["metric_id"], "label": f"{c['owner']}: {c['name']}"} for c in found[-1]["candidates"]]
        else:
            out = answer_without_model(db, question, metric_id); out["mode"] = "sin_modelo"
        out["check"] = check_evidence(out["final"], out["trace"])
        out["evidence"] = evidence_from(out["trace"])
        out["trace"] = [{k: v for k, v in t.items() if k != "result"} for t in out["trace"]]
        return out
    finally:
        db.close()
