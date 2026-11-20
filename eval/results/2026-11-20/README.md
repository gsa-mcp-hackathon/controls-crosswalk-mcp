# Evaluation results, 2026-11-20

The raw results behind the numbers in [EVALUATION.md](../../EVALUATION.md). They were exported from a local Arize Phoenix server through its REST API after the four experiments finished.

- Agent model: `gpt-5.6-luna`
- Judge model: `gpt-5.6-terra`
- Dataset: `crosswalk-eval-0`, 15 questions
- Data snapshot: `4078c6fa...37f19`

## Files

| File | What it holds |
|---|---|
| `tools-prompt-v2.json` | 15 runs. The agent with the server's tools and prompt v2. |
| `tools-prompt-v1.json` | 15 runs. The agent with the tools and prompt v1. |
| `no-tools-baseline.json` | 15 runs. The same model with no tools. |
| `tools-prompt-v2-five-runs.json` | 75 runs. Prompt v2 with tools, every question asked five times. |
| `runs.csv` | One row per run across all four experiments, 120 rows. |

Each JSON file is the experiment as Phoenix returns it from `GET /v1/experiments/{id}/json`: the question, the reference answer, the agent's answer, the time it took, and both judge labels.

`runs.csv` joins those runs with their traces. Its columns:

| Column | Meaning |
|---|---|
| `experiment` | Which of the four experiments the run belongs to |
| `question` | Question number, 1 to 15, in dataset order |
| `group` | answerable, source does not say, out of scope, or prompt injection |
| `repetition` | 1 for single runs, 1 to 5 in the five-run experiment |
| `correctness` | Label from the `match_expected_response` judge |
| `scope` | Label from the `check_answer_scope` judge |
| `seconds` | Time from question to answer |
| `tool_calls`, `tools` | How many tool calls the agent made, and which tools, in order |
| `model_calls` | How many times the agent called the model |
| `input_tokens`, `output_tokens` | Agent tokens for the run. Judge tokens are not included |
| `answer`, `expected` | The agent's answer and the reference answer |

The full traces are not included. They are about 20 MB and repeat the tool descriptions on every model call.

## Summary

| Experiment | Runs | Correct | Within scope, as judged | Mean seconds | Mean tool calls |
|---|---|---|---|---|---|
| Tools, prompt v2 | 15 | 15 | 13 | 4.1 | 2.5 |
| Tools, prompt v1 | 15 | 13 | 12 | 3.9 | 1.9 |
| No tools | 15 | 5 | 9 | 13.2 | 0 |
| Tools, prompt v2, five runs | 75 | 73 | 66 | 3.7 | 2.0 |

The scope labels on runs with tools include judge errors. See the failure analysis in [EVALUATION.md](../../EVALUATION.md).
