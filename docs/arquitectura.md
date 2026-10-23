# Arquitectura

## Flujo de una pregunta

```
pregunta ──► chat.answer()
              │
              ├─ con modelo (LM Studio)            ├─ sin modelo (reglas)
              │   el modelo decide qué llamar      │   ¿pide escribir? → se niega
              │                                    │   discover_metrics(pregunta)
              ▼                                    │   ¿0 candidatas? → «no existe»
     discover_metrics  ──►  catálogo               │   ¿más de 1? → pregunta cuál (opciones)
     query_metric      ──►  SQLite solo lectura    │   query_metric(id, versión)
              │                                    │
              └──────────────┬─────────────────────┘
                             ▼
              check_evidence(respuesta, traza)   cada número debe venir de una query_metric ok
              evidence_from(traza)               métrica, versión, período, origen, SQL, clientes
                             ▼
                     respuesta + traza + evidencia + chequeo
```

## Definir

Cada métrica es un contrato en `data/metric_contracts.json`: identificador, nombre, dueño, versión, sinónimos,
definición, grano, ventana de tiempo, frescura y linaje (archivo, tabla, columnas, filtro y agregación). Las tres
métricas de «cliente activo» conviven; ninguna corrige a las otras.

| Métrica | Regla | Valor en la base de prueba |
|---|---|---|
| `product.active_customers_login_30d` | al menos un login en `[2026-09-21, 2026-10-21)` UTC | 8 |
| `business.active_customers_transaction_30d` | al menos una transacción `posted`, importe distinto de cero, en la misma ventana | 5 |
| `finance.active_customers_positive_balance_close` | saldo mayor que cero en el cierre del 2026-10-20 | 3 |

Sin identificador explícito, `catalog.answer()` devuelve `needs_clarification` con las tres opciones. El detalle de
las reglas y los casos límite está en [catalogo.md](catalogo.md).

## Consultar

- `tools.discover_metrics(texto)` puntúa solo con las palabras que distinguen una definición de otra. «Activos» no
  distingue, así que esa pregunta queda ambigua a propósito.
- `tools.query_metric(db, {"metric_id", "version"})` rechaza parámetros extra (por ejemplo `sql`), identificadores
  desconocidos y versiones que no son la vigente. La conexión se abre con `PRAGMA query_only`: SQLite bloquea
  cualquier escritura aunque alguien la intente.
- `consumers.py` muestra que el tablero y el agente leen el mismo contrato, y que una regla copiada en el tablero
  (que también cuenta transacciones pendientes) da 6 en vez de 5. La prueba de paridad compara identificador, versión,
  período, filtro y valor.

## Comprobar

| Chequeo | Qué mira | Dónde |
|---|---|---|
| Casos de referencia | 23 expectativas con el valor escrito aparte, incluidos bordes de fecha, duplicados y estados | `data/golden_questions.json` |
| Verificador de respuestas | valor, unidad, definición, versión, período, linaje, SQL y parámetros contra el contrato | `catalog.validate_answer` |
| Número con traza | cada número del texto tiene que venir de una `query_metric` de la traza | `chat.check_evidence` |
| Verificador de tareas | el estado final de la base: una fila nueva correcta y nada más cambiado | `sandbox.verify` |
| Suite de regresión | pasa, bloquea (regresión) o alerta (datos tarde); sale con 1 si bloquea | `regression.suite` |

Un error en la consulta compartida cambia a la vez el tablero y el agente, así que la paridad no lo ve: lo atrapan
los casos de referencia, que tienen el valor esperado escrito aparte (`python3 -m agente.regression --escenario
borde_roto`).
