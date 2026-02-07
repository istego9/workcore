# ADR-0001: Expression Engine is CEL

Date: 2026-01-29
Status: Accepted

## Context
We need a safe, deterministic expression language for If/Else, While, and Set State.

## Decision
Adopt CEL (Common Expression Language) as the standard expression engine.

## Consequences
- Expressions are portable and well-defined across services.
- We must provide type validation and error reporting around CEL evaluation.
- Custom functions, if needed, must be documented and versioned.

## Alternatives Considered
- Custom DSL: higher maintenance and lower interoperability.
- Embedded JavaScript: weaker determinism and security concerns.
