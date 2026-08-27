# Evaluation datasets

**Status:** implemented, narrow coverage

## Definition
An evaluation dataset is a versioned set of cases and expectations representing behavior worth preserving. Dataset identity must change when content changes.

## Archon implementation
`backend/app/eval/datasets/grounded-v1.json` declares exact `schema_version`, `dataset_id`, semantic `version`, canonical SHA-256 `content_hash`, and two cases. `load_evaluation_fixture` rejects duplicate keys, unknown/missing fields, invalid bounds/types/version, duplicate cases/expectations, and hash drift. `EvaluationService` allowlists dataset paths and requires every case key exactly once with unique run IDs.

## Design guidance
Cases should represent real distributions, edge cases, abstention, adversarial failures, and subgroups. Keep prompts/expected behavior under review, freeze test sets before comparing changes, and separate development from holdout data.

## Evidence and limits
`backend/tests/unit/test_evaluation_fixtures.py`, `backend/tests/unit/test_recorded_evaluations.py`. The shipped two-case deterministic fixture proves loader/evaluator behavior and selected grounded/abstention regressions; it is not representative model-quality evidence.

## Interview prompt
“Version plus canonical hash makes fixture drift visible; representativeness and annotation quality still require separate evidence.”
