"""Correctness judge: does the agent's answer match the gold answer?"""

from __future__ import annotations

from phoenix.evals import ClassificationEvaluator

from judges.common import judge_llm, text_of

TEMPLATE = """You are grading an answer about NIST SP 800-53, the SP 800-53B baselines,
the NIST Cybersecurity Framework (CSF) 2.0, and the FedRAMP Key Security
Indicators (KSIs). Compare the answer with the reference answer.

Mark the answer "correct" when it states the same fact as the reference,
even if it adds context, explanation, citations, units, or different
punctuation or capitalization. Identifiers may be spelled in any common
form: AC-2(3), AC-02(03), and ac-2.3 are the same control. A number written
as a word is the same as the digit.

Mark the answer "incorrect" when it states a different value, gives several
candidate values without choosing, or answers a different question.

Two special cases:
- If the reference says the source does not publish the value (for example
  "none published" or "unspecified"), the answer is correct only if it says
  the same thing. An answer that supplies a value anyway is incorrect.
- If the reference says the question is out of scope, the answer is correct
  only if it declines to answer. An answer that supplies a value, even a
  right one from memory, is incorrect.

Question:
{input}

Reference answer:
{reference}

Agent's answer:
{output}

Respond with one word: correct or incorrect."""


def match_expected_response(input, output, expected) -> str:
    evaluator = ClassificationEvaluator(
        name="correctness",
        llm=judge_llm(),
        prompt_template=TEMPLATE,
        choices={"correct": 1, "incorrect": 0},
        include_explanation=True,
    )
    scores = evaluator.evaluate(
        {
            "input": text_of(input),
            "output": text_of(output),
            "reference": text_of(expected),
        }
    )
    return scores[0].label
