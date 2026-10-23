# ADR 0002 · Modelo local con LM Studio y modo sin modelo

**Estado:** aceptada · 2026-10-23

## Contexto

El chat tiene que funcionar como lo usaría alguien de negocio, pero los datos de una empresa no deberían salir de la
computadora para probar un agente. Además, quien clona el repositorio puede no tener ningún modelo instalado.

## Decisión

- Por defecto, el cliente (`agente/llm.py`) habla con LM Studio en `http://localhost:1234/v1`, con la API compatible
  con OpenAI. Elige el modelo cargado, o uno de una lista probada (`google/gemma-4-26b-a4b` primero).
- Cualquier otro servidor compatible se configura con `AGENTE_BASE_URL`, `AGENTE_MODEL` y `AGENTE_API_KEY`.
- Si no hay modelo, el chat responde **sin modelo** con el mismo proceso: búsqueda en el catálogo, aclaración ante la
  ambigüedad, consulta por identificador y versión, y chequeo de evidencia.
- En los dos modos, el chequeo `check_evidence` marca cualquier número de la respuesta que no venga de una consulta.

## Consecuencias

- La aplicación nunca queda inutilizable por falta de modelo; la pantalla dice qué modo respondió.
- El modo sin modelo no entiende lenguaje natural: cubre las preguntas que usan palabras del catálogo.
- Las evaluaciones con modelo (`evals/`) quedan fuera de las pruebas automáticas y guardan sus resultados.
