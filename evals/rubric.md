# Judge rubric

The judge scores each golden-set answer on three metrics, from 1 (worst) to 5 (best). The live stage sends this file
to the judge model; the offline gate reads the recorded scores.

| Score | Correctness | Faithfulness | Completeness |
| --- | --- | --- | --- |
| 5 | Every fact matches the reference answer | Every claim is supported by the retrieved context | Covers every point in the reference |
| 4 | One minor imprecision that would not mislead a customer | One small claim not in the context, harmless | Misses one secondary detail |
| 3 | One fact is wrong or missing that changes what the customer does | Adds a claim not in the context that could mislead | Misses a point the customer needs |
| 2 | Several facts wrong, or the main fact wrong | Mostly not grounded in the context | Answers only part of the question |
| 1 | Wrong or harmful | Contradicts the context | Does not answer the question |

Rules for the judge:

- Score against the reference answer and the retrieved context only, not general knowledge.
- A shorter answer that keeps every fact scores 5 on completeness.
- Deadlines, amounts, fees and eligibility are facts. A wrong number is at most 3 on correctness.
- Return one JSON object: `correctness`, `faithfulness`, `completeness` (integers) and a one-sentence `rationale`.
