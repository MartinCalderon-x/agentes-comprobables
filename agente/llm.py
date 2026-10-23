"""Cliente mínimo de modelos con el formato de chat de OpenAI. Solo biblioteca estándar.

Por defecto habla con LM Studio en esta computadora (http://localhost:1234/v1): sin clave y sin enviar datos afuera.
Configuración por variables de entorno:

  AGENTE_BASE_URL   servidor compatible con OpenAI (por defecto, LM Studio local)
  AGENTE_MODEL      modelo a usar; si no se define, se elige uno cargado en LM Studio
  AGENTE_API_KEY    solo para servidores remotos (por ejemplo https://openrouter.ai/api/v1)

Cada corrida devuelve la traza de llamadas a herramientas, los tokens que informa el servidor y la latencia medida
de punta a punta.
"""
import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("AGENTE_BASE_URL", "http://localhost:1234/v1").rstrip("/")
LOCAL = any(h in BASE_URL for h in ("localhost", "127.0.0.1", "0.0.0.0"))
API_KEY = os.environ.get("AGENTE_API_KEY", "")
# Modelos probados con este proyecto, en orden de preferencia, si no se define AGENTE_MODEL
PREFERRED = ["google/gemma-4-26b-a4b", "google/gemma-4-e4b", "qwen/qwen3-8b", "google/gemma-3-12b"]
SKIP = ("embed", "whisper", "tts", "rerank")
MODEL = os.environ.get("AGENTE_MODEL", "")


def _request(path, payload=None, timeout=600):
    headers = {"Content-Type": "application/json", "User-Agent": "agentes-comprobables"}
    if API_KEY and not LOCAL: headers["Authorization"] = f"Bearer {API_KEY}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode("utf-8"))
        except Exception: return {"error": {"message": f"HTTP {e.code}", "code": e.code}}
    except Exception as e:  # servidor apagado, sin red, timeout
        return {"error": {"message": str(e), "code": "unavailable"}}


def _loaded_lmstudio_models():
    """LM Studio informa qué modelos están cargados en memoria en /api/v0/models (fuera de /v1)."""
    root = BASE_URL[:-3] if BASE_URL.endswith("/v1") else BASE_URL
    req = urllib.request.Request(root + "/api/v0/models", headers={"User-Agent": "agentes-comprobables"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8")).get("data", [])
        return [m["id"] for m in data if m.get("state") == "loaded" and m.get("type", "llm") in ("llm", "vlm")]
    except Exception:
        return []


def pick_model():
    """Elige el modelo: AGENTE_MODEL, o uno cargado en LM Studio, o uno de la lista probada, o el primero de chat."""
    global MODEL
    if MODEL: return MODEL
    data = _request("/models", timeout=5)
    ids = [m["id"] for m in data.get("data", []) if not any(s in m["id"].lower() for s in SKIP)]
    if not ids: return ""
    loaded = [m for m in _loaded_lmstudio_models() if m in ids] if LOCAL else []
    MODEL = next((m for m in loaded), None) or next((m for m in PREFERRED if m in ids), None) or ids[0]
    return MODEL


def status():
    """Estado del modelo para la pantalla: si responde, cuál es y dónde corre."""
    if not LOCAL and not API_KEY:
        return {"available": False, "local": False, "base_url": BASE_URL, "reason": "Falta AGENTE_API_KEY para un servidor remoto."}
    data = _request("/models", timeout=5)
    if "error" in data:
        return {"available": False, "local": LOCAL, "base_url": BASE_URL,
                "reason": "LM Studio no responde. Ábrelo y enciende el servidor local." if LOCAL else data["error"].get("message", "")}
    model = pick_model()
    return {"available": bool(model), "local": LOCAL, "base_url": BASE_URL, "model": model,
            "reason": "" if model else "No hay un modelo de chat disponible en el servidor."}


def chat(payload, retries=3):
    for attempt in range(retries):
        t0 = time.perf_counter()
        data = _request("/chat/completions", payload)
        ms = (time.perf_counter() - t0) * 1000
        code = (data.get("error") or {}).get("code")
        if code in (429, 500, 502, 503) and attempt < retries - 1:
            time.sleep(4 * (attempt + 1)); continue
        return data, ms
    return data, ms


def oa_tools(tools):
    return [{"type": "function", "function": t} for t in tools]


def run_agent(question, system, tools, executor, max_turns=6, temperature=0.0, context=None, history=None):
    """Bucle de herramientas. `context` (opcional) va como mensaje de sistema adicional y `history` son turnos previos
    [{"role": "user"|"assistant", "content": ...}]. Devuelve la traza, el texto final, los tokens y la latencia."""
    model = pick_model()
    if not model:
        return {"error": "no hay modelo disponible", "trace": [], "latency_ms": 0}
    msgs = [{"role": "system", "content": system}]
    if context: msgs.append({"role": "system", "content": context})
    msgs += history or []
    msgs.append({"role": "user", "content": question})
    trace, usage, total_ms, model_version = [], {"prompt": 0, "output": 0}, 0.0, None
    for _ in range(max_turns):
        payload = {"model": model, "messages": msgs, "temperature": temperature}
        if not LOCAL: payload["usage"] = {"include": True}
        if tools: payload["tools"] = oa_tools(tools)
        data, ms = chat(payload); total_ms += ms
        if data.get("error"):
            return {"error": str(data["error"].get("message", ""))[:300], "trace": trace, "latency_ms": round(total_ms)}
        model_version = data.get("model", model_version)
        u = data.get("usage") or {}
        usage["prompt"] += u.get("prompt_tokens", 0); usage["output"] += u.get("completion_tokens", 0)
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"final": (msg.get("content") or "").strip(), "trace": trace, "usage": usage,
                    "latency_ms": round(total_ms), "model": model_version}
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            try: args = json.loads(c["function"].get("arguments") or "{}")
            except Exception: args = {"_raw": c["function"].get("arguments")}
            result = executor(c["function"]["name"], args)
            trace.append({"tool": c["function"]["name"], "args": args, "status": result.get("status"),
                          "value": result.get("value"), "result": result})
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, ensure_ascii=False)})
    return {"final": None, "trace": trace, "usage": usage, "latency_ms": round(total_ms), "error": "max_turns",
            "model": model_version}
