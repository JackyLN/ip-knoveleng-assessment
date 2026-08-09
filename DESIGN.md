# StayFlow design report

## Architecture and responsibility boundaries

StayFlow uses a controlled single-agent workflow because the assessment has one bounded objective and five read-only tools. A multi-agent design would add handoffs, duplicated context, latency, cost, and harder failure analysis without improving this small workflow. One orchestrator therefore owns the fixed sequence: validate intake, classify, retrieve, review, draft, and validate.

The LLM handles tasks where language interpretation is useful: structured classification, selecting retrieval tools in OpenAI mode, and proposing a concise report. Deterministic Python remains authoritative for workflow order, tool schemas and execution, category-required lookups, duplicate/unknown-call rejection, source-ID validation, allowed actions, approval flags, report status, and human-review decisions. The application never performs a booking, refund, payment, relocation, or other business action.

## Tool calling, grounding, and failures

The OpenAI Responses API receives strict function schemas. The model requests a tool, the application validates its arguments, executes the corresponding JSON-backed Python function, and returns structured results to the model. Tool selection is limited to five turns; the orchestrator performs any required lookup the model omitted. Reports receive only original feedback, validated classification, retrieved guest/booking/property records, workflow and policy records, and deterministic review output. References are accepted only when IDs and titles match retrieved records; actions must exactly match the retrieved workflow's allowlist.

Missing records remain `null` or empty and make context partial. Low-confidence, vague, multi-issue, and out-of-domain classifications are marked ambiguous. Conflicting guest claims and booking records are presented neutrally. Classification, tool, or report-provider failures produce controlled fallback state, retain available context, appear in the safe execution trace, and require review. Prompt content is treated as untrusted data rather than instructions.

## Human review

The result page shows the proposed action, supporting sources, approval requirement, missing data, contradictions, and deterministic review reasons. A CS officer verifies those sources, may reject or edit the recommendation in the downstream case system, and must record an approval before any operational or financial action. An override should preserve the original report, officer identity, timestamp, reason, and replacement decision. This prototype displays the review contract but deliberately does not persist or execute approvals.

## Production readiness

- **Reliability:** persistent job state, idempotency, circuit breakers, provider fallback, schema/version migration, and monitored service-level objectives.
- **Evaluation:** labeled production-like cases, adversarial suites, human quality review, drift monitoring, and release gates for classification, grounding, and unsafe-action rates.
- **Cost and latency:** smaller-model routing, token budgets, caching stable policy context, parallel independent reads, usage quotas, and per-stage metrics.
- **Security and privacy:** authenticated role-based access, secret management, encryption, data minimisation/redaction, retention controls, audit logs, and regional/compliance review.
- **Persistence and integrations:** a transactional database and immutable review history, plus authenticated CRM/PMS, policy, identity, payment, and ticketing adapters with least-privilege permissions.

## Deliberate exclusions

Real hotel integrations, autonomous actions, durable approval UI, databases, queues, vector search, multi-agent handoffs, policy/legal interpretation, multilingual handling, and model training were left out to keep the assessment focused on structured output, real tool calling, grounding, deterministic control, review, failure handling, and observability.
