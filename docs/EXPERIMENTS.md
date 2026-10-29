# Running and reproducing experiments

## Benchmark tasks

`benchmarks/tasks/<id>/` holds:

| Path | Purpose |
|---|---|
| `task.json` | id, category, difficulty, requirement (what the agents see), acceptance criteria |
| `repo/` | starting repository with visible tests |
| `hidden_tests/` | grading tests; never copied into an agent workspace |
| `solution/` | reference solution, used only to validate the task |

There are 10 tasks covering bug fix, feature (×2), error handling, refactoring, API, security, performance, configuration and database. `tests/test_evaluation.py::test_every_task_is_valid` checks three properties for every task: the visible tests pass on the starting repo, the hidden tests fail on it, and the reference solution passes everything.

To add a task, create the four parts and run that test.

**Grading** (`backend/evaluation/benchmark.py`) copies the final workspace into a separate grading workspace, adds the hidden tests and runs hidden and visible suites in the sandbox:

- `task_success`: all hidden tests and all visible tests pass.
- `hidden_pass_rate`: passed / collected hidden tests.
- `regression`: any visible test fails.

Agent self-reports (`verified`) are stored separately, so verifier calibration can be measured (`verifier_false_positive`).

## Configuring an experiment

```json
{
  "name": "pilot-real-architectures",
  "execution_mode": "real",
  "tasks": ["bugfix_pagination", "feature_modulo", "security_safe_join"],
  "architectures": ["sequential", "hierarchical", "event_driven", "blackboard"],
  "prompt_variants": ["baseline"],
  "models": [{"provider": "groq", "model": "groq/llama-3.3-70b-versatile",
              "input_cost_per_1m": 0.59, "output_cost_per_1m": 0.79}],
  "repeats": 3,
  "seed": 1234,
  "temperature": 0.1,
  "debug_max_iter": 3,
  "tool_transport": "mcp",
  "verifier_backend": "crewai",
  "max_cost_usd": 5.0
}
```

The prices above are examples only. Fill in your provider's current prices. If prices are missing, costs are reported as `n/a`, and `max_cost_usd` is refused because it could not be enforced. Templates: `benchmarks/experiments/pilot_mock.json`, `pilot_real_template.json`.

**Factors**: `architectures`, `prompt_variants` (`baseline | react | few_shot | minimal_persona`) and `models`. Everything else is held constant.

## Running from the dashboard

The **Experiments** page lists only options the server actually supports (`GET /experiments/options`; RAG is shown as unavailable). **Validate** reports the trial count, errors (e.g. real mode without a key) and warnings before anything runs; **Start** returns the experiment id immediately and the job runs in the background (an identical running configuration is rejected to prevent double starts). Progress, **Cancel** (between trials), **Resume missing trials** (after cancel, failure or a backend restart — interrupted experiments are detected at startup), per-run results with links to each run's report and trace, architecture and prompt comparisons, and exports are on the same page. Real mode requires ticking the cost confirmation; an API key entered there is used for that job only and never stored.

API: `POST /experiments/validate`, `POST /experiments`, `POST /experiments/{id}/cancel`, `POST /experiments/{id}/resume`, `GET /experiments/{id}/runs`, `GET /experiments/{id}/summary`.

## Running from the CLI

```bash
# validates the whole pipeline; no LLM, no cost
.venv/bin/python -m backend.evaluation.experiment benchmarks/experiments/pilot_mock.json

# real mode (calls your LLM provider and costs money)
.venv/bin/python -m backend.evaluation.experiment my_config.json

# continue an interrupted experiment; completed trials are skipped
.venv/bin/python -m backend.evaluation.experiment my_config.json --resume exp-20261027-101500-ab12cd
```

Trials are the full factorial task × architecture × variant × model × repeat, shuffled with `seed`, so slow drifts such as provider latency or rate limits don't line up with one condition. Each trial starts from a fresh copy of the task repository.

Mock experiments make no code changes, so tasks fail grading by design. Use them to check the setup and to measure coordination overhead, not capability.

## Results

Raw data:

- the registry (`runs` and child tables), including the full `RunResult` JSON per run,
- `experiments/<id>/raw_runs.jsonl` next to the registry database (`VEXA_DB_PATH`, default `data/`).

The environment (Python and package versions, platform, config hash) is stored with the experiment.

Derived statistics (`backend/evaluation/stats.py`) are always recomputed from raw rows:

| Metric | Notes |
|---|---|
| task success, regression, run failure, timeouts, verifier false positives | proportion with count and Wilson 95% CI |
| hidden-test pass rate, latency, debug iterations, LLM/tool calls | mean, sd, median, p90 |
| tokens, estimated cost | averaged only over runs that reported usage / had prices; the count is shown |
| repeatability | tasks whose repeats all agree, per-task sd |
| architecture comparisons | success-rate difference with Newcombe 95% interval |
| bottlenecks | share of agent time per agent |

Export from the dashboard's Experiments page or the API:

```
GET /experiments/{id}/summary
GET /experiments/{id}/export?format=csv|json|md
```

## Reproducing someone else's experiment

1. Check out the same commit and install the same package versions (listed in the experiment's `environment`).
2. Run the stored `config` with the same `seed`.
3. LLM sampling is not bit-reproducible even at low temperature, so compare distributions (the intervals above), not individual runs.
