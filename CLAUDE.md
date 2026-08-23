# UrbanoPay Mobilidade

AI-assisted urban mobility sales platform built as a portfolio-grade end-to-end product.

## Before making changes

Always inspect the repository and read the relevant project documentation before implementation.

Authority order:

1. `docs/prd/PRD.md` defines product scope and objectives.
2. `docs/specs/` defines expected functional behavior.
3. `docs/adr/` defines accepted architectural decisions.
4. `docs/agent-harness/AGENT-HARNESS.md` defines the development governance model.
5. Implementation must conform to the documents above.

If code, SPEC, PRD, or ADR conflict, do not silently choose one. Report the conflict before changing behavior.

## Core architecture

- Monorepo.
- Modular monolith.
- Backend: Python + FastAPI.
- Agent orchestration: LangGraph.
- Runtime architecture: one conversational Sales Agent.
- Business domains are deterministic services, not additional runtime agents.
- PostgreSQL is the transactional source of truth.
- pgvector is restricted to semantic retrieval.
- Redis is restricted to ephemeral operational state.
- Mercado Pago test environment is used for Pix payments.
- OpenTelemetry provides transversal telemetry.
- Langfuse provides LLM/agent observability.
- Runtime LLM access must use a provider/model abstraction.

## Critical architectural rule

The LLM interprets, recommends and explains.

Code validates, calculates, authorizes, transitions state, executes and persists.

Never move deterministic business rules into prompts.

## Runtime agent restrictions

The Sales Agent must never receive generic capabilities such as:

- arbitrary SQL execution;
- arbitrary HTTP requests;
- shell execution;
- direct balance modification;
- direct fare modification;
- direct payment status modification;
- direct order status modification;
- direct fare-profile modification.

Expose narrow typed tools backed by application services.

## Financial rules

- Never use float for money.
- Use Decimal in Python.
- Use NUMERIC/DECIMAL in PostgreSQL.
- Financial operations must be idempotent.
- User messages never prove payment.
- Only the payment provider/backend may establish `PaymentStatus.APPROVED`.
- Fulfillment can only occur after an approved payment and paid Order.
- A fulfillment failure after payment must never create another charge automatically.

## Data and security

- Never commit secrets.
- Never expose credentials to the LLM.
- Never log OTP values.
- Never log full CPF or full transport-card numbers.
- Validate authentication and ownership server-side.
- PostgreSQL remains authoritative for transactional state.
- Vector search must never be authoritative for prices, balances or payment state.

## Database changes

All schema changes require versioned migrations.

Do not make destructive migrations without explicit review.

Use database constraints for critical invariants whenever practical.

## Testing

Behavior changes require tests.

- Domain rules: unit tests.
- Database/provider boundaries: integration tests.
- Full purchase journeys: end-to-end tests.
- Probabilistic agent behavior: evals.
- Bug fixes require regression tests.

Never delete, skip or weaken a test merely to make CI pass.

## Git workflow

Never implement directly on `main`.

Use a dedicated branch for each coherent task.

Use Conventional Commits.

Do not force-push.

Do not commit or push unless explicitly requested or the current workflow clearly requires it.

Before considering a task complete:

1. inspect the diff;
2. run relevant tests;
3. run lint/type checks when configured;
4. verify relevant SPEC and ADR compliance;
5. report remaining risks or unresolved issues.

## Architectural changes

New infrastructure, providers, major dependencies, state-machine changes or domain-boundary changes require an ADR before implementation.

Do not silently introduce architectural decisions.

## Initial project phase

The repository is currently in bootstrap phase.

Do not invent missing business rules.

When information is missing, preserve the existing architecture and identify the unresolved decision.