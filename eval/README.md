# Evaluation

Two layers check this server, one without a model and one with.

## 1. Gold answers, no model

`eval/phoenix/datasets/crosswalk-eval-0/evaluation.xml` holds twelve questions with verified answers: nine answerable, two where the correct answer is that the source does not say, and one out of scope. `eval/gold_check.py` answers each one by calling the server's tools, the way an agent would, and compares the result with the recorded answer.

```bash
uv run eval/gold_check.py
```

It runs in a second and needs only the built store. It is also a pytest test, so `uv run pytest` runs it whenever `data/crosswalk.sqlite` exists. Run it after refreshing the data snapshot; if a publisher changed a file, this shows which answers moved.

## 2. Agent plus judges, with a model

`eval/phoenix/` is the [Arize Phoenix](https://docs.arize.com/phoenix) harness from the template's `mcp-eval` skill. It launches this server over stdio, connects a LangChain agent to it, asks each gold question, and scores every answer with two LLM judges: one for correctness against the gold answer, one for staying within scope. Traces of every tool call land in the Phoenix UI, which is where you see why a question failed.

See [phoenix/README.md](phoenix/README.md) for setup and the run commands. It needs an OpenAI-compatible gateway key (the USAi gateway for the hackathon) and the `eval` dependency group.

## What to record in the evaluation document

- Correctness and scope scores per prompt version, from the Phoenix experiment.
- Which questions failed and whether the fix was in a tool description, the system prompt, or the question.
- The gold check result and the snapshot hash it ran against.
- Tool latency from the deterministic tests and a cold build time.

## Databricks

`eval/databricks/` is the template's kit for evaluating a deployed Databricks App with MLflow judges. It is not used by this project and is left as the template shipped it.
