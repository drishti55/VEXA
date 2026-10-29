# VEXA — Project Specification

> **Source of truth.** Do not modify this document without explicit team review.

---

## Project Identity

| Field | Value |
|---|---|
| **Project Name** | VEXA |
| **Full Name** | Architecture-Aware Autonomous Multi-Agent Software Engineering System |
| **Type** | Final-year Engineering / Research Project |
| **Primary Framework** | CrewAI |
| **Backend** | Python, FastAPI |
| **Database** | PostgreSQL |

---

## Primary Purpose

VEXA autonomously converts natural-language software requirements into working software and can modify/debug existing software repositories.

It also experimentally compares three distinct multi-agent orchestration architectures performing the same software-engineering tasks, producing measurable research data on architecture effectiveness.

---

## Operating Modes

VEXA supports two execution modes:
- **Mock Mode:** Deterministic execution without an LLM. Used for 198+ CI/CD unit and integration tests.
- **Real Mode:** Live execution using an actual LLM provider (e.g. OpenAI). Safe and restricted to the sandboxed workspace.

### A. BUILD MODE

```
Natural-language requirement
    → Requirement Analysis
    → Planning
    → Architecture / Design
    → Code Generation
    → Testing
    → Debugging (iterative, up to MAX_ITERATIONS)
    → Verification
```

### B. MODIFY MODE

```
Existing repository
    → Codebase Understanding (Project Analyst + RAG)
    → Planning
    → Code Modification
    → Testing
    → Debugging (iterative, up to MAX_ITERATIONS)
    → Verification
```

---

## Core Agents

| # | Agent | Responsibility |
|---|---|---|
| 1 | **Requirement Analyst** | Parse and structure user requirements; identify constraints and acceptance criteria |
| 2 | **Project Analyst** | Inspect existing repositories; produce a project context map |
| 3 | **Planner** | Produce an ordered implementation plan from requirements + project context |
| 4 | **Coder** | Generate and modify source code files based on the plan |
| 5 | **Tester** | Generate test cases and execute them; return structured results |
| 6 | **Debugger** | Analyse failures; identify root cause; produce a patch strategy |
| 7 | **Verifier** | Confirm all original requirements are satisfied with no regressions |

> **Design principle:** Every agent must have a single, well-defined responsibility. Do not create agents without clear justification.

---

## Core Orchestration Architectures

### 1. Sequential

```
Analyst -> Planner -> Coder -> Tester -> Debugger -> Verifier
```

Each agent waits for the previous one to complete. Linear, predictable, low coordination overhead. Provides a clear performance baseline.

### 2. Hierarchical

```
Manager Agent
  +-- Analyst
  +-- Planner
  +-- Coder
  +-- Tester
  +-- Debugger
  +-- Verifier
```

A Manager agent delegates tasks and decides control flow. Closer to a real engineering team structure. Can express more complex coordination.

### 3. Event-Driven

Agents subscribe to events rather than being called directly.

```
CODE_CHANGED -> Tester wakes
TEST_FAILED  -> Debugger wakes
PATCH_READY  -> Coder wakes
TEST_PASSED  -> Verifier wakes
```

Decoupled, reactive orchestration. Potentially higher parallelism; higher coordination complexity.

---

## Important Research Principle

> **The three architecture implementations must use the same underlying agents, tools, prompts/configuration, benchmark tasks, and evaluation definitions wherever possible.**
>
> The primary experimental variable is the **orchestration architecture**.
> This is what makes the comparison scientifically meaningful.
>
> Do not casually change this research objective.

---

## Required Future Infrastructure

The following components are **not implemented in Milestone 1** but must be planned for:

| Component | Purpose |
|---|---|
| Project RAG | Code-aware retrieval for MODIFY mode |
| Agent Tools | File I/O, git, AST analysis, execution |
| MCP | Tool interoperability layer |
| Memory | Short-term (run), project, long-term |
| Sandboxed Execution | Docker-isolated code execution |
| Guardrails / Safety | Prevent dangerous code execution |
| Observability / Tracing | Per-run structured traces |
| Evaluation Framework | Automated metric collection |
| Benchmark Runner | Controlled task execution |
| Frontend Dashboard | Real-time execution view + research metrics |

---

## Primary Experimental Variables

| Variable | Options |
|---|---|
| Architecture | Sequential, Hierarchical, Event-Driven |
| LLM / Model | Configurable per agent and per run |
| Prompt Strategy | Structured, ReAct, COTS |
| RAG | Enabled / Disabled |
| Communication Mechanism | Blackboard, P2P, MCP |

---

## Primary Evaluation Metrics

### Run-Level Metrics
- Task success rate
- Test pass rate
- Requirement satisfaction (verified)
- Regression rate
- Total latency
- Total token usage
- Estimated LLM cost
- Number of iterations

### Agent-Level Metrics
- Per-agent latency
- Per-agent token usage
- Per-agent estimated cost
- Per-agent failure rate
- Agent bottleneck identification

---

## Benchmark Target

| Requirement | Value |
|---|---|
| Minimum runs (course guideline) | **40** |
| Target benchmark task count | **50** |
| Task categories | Bug Fix, Feature, Refactoring, Testing, Error Handling, API, Database, Performance, Configuration, Security |

Each benchmark task will have:
- A target repository (controlled, small/medium Python project)
- A natural-language issue description
- Expected behaviour
- Deterministic test cases
- Ground truth

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent Framework | **CrewAI** |
| Backend | Python 3.11+, FastAPI |
| Database | PostgreSQL |
| Vector DB | FAISS / ChromaDB |
| Sandbox | Docker |
| Observability | Structured logging -> OpenTelemetry (future) |
| Frontend | React (future milestone) |

---

## Milestone Plan (High Level)

| Milestone | Focus |
|---|---|
| M1 - Foundation | Project structure, FastAPI, core models, config, Docker, tests |
| **M2 - Tool Layer** | Agent tools, sandboxed execution, file I/O |
| M3 - Agent Definitions | CrewAI agents, prompts, tool assignments |
| M4 - Sequential Architecture | First working end-to-end VEXA run |
| M5 - Hierarchical Architecture | Manager + sub-agent orchestration |
| M6 - Event-Driven Architecture | Event bus, agent subscriptions |
| M7 - RAG | Code-aware retrieval for MODIFY mode |
| M8 - Observability + Evaluation | Per-run traces, metrics collection |
| M9 - Benchmark Runner | Automated 50-task benchmark execution |
| M10 - Frontend Dashboard | Live execution view, research comparison |

---

*Last updated: 2026-09-21 | Milestone: M3.5 - Real LLM Integration*
