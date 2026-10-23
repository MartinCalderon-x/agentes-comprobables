# Demo: tres definiciones de «cliente activo»

Ejercicio educativo autocontenido en español, con Python 3 y SQLite de la biblioteca estándar. No instala dependencias ni usa credenciales, servicios externos, red o llamadas a un LLM. La base se crea en memoria en cada ejecución; no modifica bases reales.

## Ejecutar

Desde esta carpeta `demo`:

```sh
python3 demo.py
python3 -m unittest -v
```

Para guardar evidencia y consultar una métrica explícita:

```sh
python3 demo.py > results.log
python3 demo.py --json > results.json
python3 -m unittest -v > test-results.log 2>&1
python3 demo.py --metric-id business.active_customers_transaction_30d
```

## Resultado esperado y verificado

- Producto: **8** clientes distintos con al menos un login.
- Negocio: **5** clientes distintos con al menos una transacción monetaria contabilizada.
- Finanzas: **3** clientes distintos con saldo positivo al cierre.
- **23/23 casos golden** correctos y **30 tests unittest** aprobados. Los tests cubren y amplían esos casos; no son preguntas independientes adicionales.
- La respuesta deliberadamente incorrecta `Negocio=8` es rechazada.

Los contratos son métricas diferentes, con identificadores separados. Ninguna definición reemplaza o «corrige» a las demás. Una respuesta canónica necesita el `metric_id`, el período y la versión adecuados; no significa que exista un único número universal de clientes activos.

## Reglas exactas

La ventana de Producto y Negocio es de 30 días UTC:

`[2026-09-21T00:00:00Z, 2026-10-21T00:00:00Z)`

El inicio está incluido y el final excluido. Fechas y reloj son fijos para reproducibilidad, no se calculan respecto del día en que se ejecuta el programa. Todos los timestamps de este dataset tienen el mismo formato UTC normalizado, por lo que la comparación de cadenas en SQLite conserva el orden temporal. En un sistema real se necesitan validación y normalización de timestamps.

- **Producto** (`product.active_customers_login_30d`): al menos un login en la ventana. Dos eventos del mismo cliente cuentan una vez. Miembros: `c01` a `c08`.
- **Negocio** (`business.active_customers_transaction_30d`): al menos una transacción con `status='posted'` e `amount_cents != 0` en la ventana. Se excluyen cero, `reversed` y `pending`. Un reembolso negativo `posted` **sí cuenta** según este contrato ilustrativo. No se netean importes por cliente ni se mide ingreso. Miembros: `c01` a `c05`.
- **Finanzas** (`finance.active_customers_positive_balance_close`): `balance_cents > 0` en el snapshot de cierre del **2026-10-20 UTC**, al finalizar ese día, antes de `2026-10-21T00:00:00Z`. No es una ventana de actividad de 30 días, sino un stock al cierre. Miembros: `c01`, `c06`, `c10`. El snapshot contiene los 12 clientes, incluidos saldos cero y negativos; no se toman saldos de otras fechas.

Todos los importes son enteros en centavos USD. El dataset es totalmente sintético, de 12 clientes, y está diseñado para exponer casos límite, no para representar una distribución comercial real. El owner es un rol ficticio.

## Ambigüedad y proveniencia

Ante `¿Cuántos clientes activos tenemos?`, sin `metric_id`, el harness devuelve `needs_clarification` y ofrece Producto, Negocio o Finanzas; no elige silenciosamente. El mismo sinónimo aparece deliberadamente en los tres contratos.

Con un `metric_id` válido responde con valor, unidad, definición y proveniencia: owner, versión de métrica/dataset, ventana o snapshot, frescura sintética, archivo y columnas de origen, SQL realmente ejecutado, parámetros y clientes incluidos. Un identificador desconocido devuelve `unknown_metric` y el CLI sale con código 2.

La frescura se calcula usando el instante fijo `2026-10-21T02:00:00Z` y metadatos de ejemplo que declaran datos completos hasta las 00:00 UTC: **2 horas**, dentro del SLA ilustrativo de 24 horas. No prueba una ingesta real, no garantiza datos actuales y no bloquea automáticamente una respuesta si cambia ese estado.

## Prueba negativa reproducible

```sh
python3 demo.py --mutate-lower-bound > mutation-results.log 2>&1
echo $?
```

La segunda línea debe mostrar **1**. Esa opción cambia deliberadamente `>=` por `>` para excluir por error el inicio. No altera archivos ni contratos. Resultado: Producto pasa de 8 a 7 y Negocio de 5 a 4; Finanzas permanece en 3. Fallan cuatro casos golden y se muestran esperado y observado:

```text
FAIL product_count: value: expected=8, actual=7; provenance.executed_sql differs from canonical contract
FAIL business_count: value: expected=5, actual=4; provenance.executed_sql differs from canonical contract
FAIL login_lower_included: expected=1, actual=0
FAIL transaction_lower_included: expected=1, actual=0
RESULTADO: FAIL
```

Es una falla intencional. La suite normal prueba que el proceso mutado falla: por eso `python3 -m unittest -v` termina correctamente aunque incluya esta prueba negativa. No interpretar la salida 1 del comando mutado como una avería de la versión normal.

## Qué demuestra y qué no

Demuestra selección explícita de un contrato, consulta SQL determinista, trazabilidad y comprobaciones contra resultados esperados independientes. Incluye límites temporales, eventos repetidos, estados de transacción, importe cero, reembolso, snapshot de saldo, ambigüedad y métrica desconocida.

**No es la ejecución de un agente LLM.** No interpreta lenguaje natural: sin `metric_id` siempre pide elección, aunque el texto parezca específico. Los sinónimos son metadatos de contrato, no un clasificador. El código SQL está permitido explícitamente, no se genera a partir de la pregunta. Los contratos describen las reglas, pero no son un motor genérico que compile cualquier definición.

El evaluador compara los resultados esperados y exige coincidencia exacta con el contrato en definición, unidad, owner, versiones de métrica/dataset, período, lineage, metadatos de frescura y corte de evaluación. También exige el SQL permitido y los parámetros canónicos, y comprueba consistencia y unicidad de los IDs. La suite incluye rechazos específicos para versiones, períodos, lineage, frescura, SQL y parámetros alterados.

Sigue siendo un evaluador estrecho, no universal: la igualdad del texto SQL no demuestra que un sistema externo realmente haya ejecutado esa consulta; no admite SQL alternativo aunque sea equivalente. No certifica semántica general, seguridad, exactitud de fuentes externas ni resistencia a respuestas adversariales. Para evaluar Claude u otro modelo, se debe ejecutar por separado un sistema que produzca respuestas con este esquema y contrastarlas con estos casos, sin presentar estos resultados como rendimiento de ese modelo. No se reportan métricas de tokens, calidad LLM, costo o latencia.

## Archivos

- `demo.py`: ejecución y evaluador determinista.
- `data.sql`: esquema y datos sintéticos transparentes.
- `metric_contracts.json`: contratos separados con owner, versión, sinónimos, tiempo, frescura y lineage.
- `golden_questions.json`: 23 expectativas explícitas, incluidas preguntas y comprobaciones de miembros.
- `test_demo.py`: 30 tests y prueba de mutación mediante proceso separado.
- `results.json`, `results.log`: salida completa y resumen de la ejecución normal.
- `test-results.log`: evidencia de la suite.
- `mutation-results.log`: evidencia de la falla intencional.
