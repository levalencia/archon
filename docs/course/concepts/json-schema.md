# JSON Schema for Archon tools

## Definition

JSON Schema describes allowed JSON structure. Archon deliberately implements a compact subset for tool arguments; do not infer support for the entire standard.

```json
{
  "type": "object",
  "properties": {"city": {"type": "string"}},
  "required": ["city"],
  "additionalProperties": false
}
```

## Supported subset

The root is an object. `required` is a unique string array; `properties` maps names to declarations; `additionalProperties` is boolean. Property types are `string`, `integer`, `number`, `boolean`, `object`, and `array`; `enum` is supported with type-sensitive equality. Numbers must be finite. Unknown fields fail unless explicitly allowed.

Registration metadata is validated and recursively frozen by [`_validate_input_schema` and `_deep_freeze`](../../../backend/app/tools/registry.py). Calls are checked by [`SecureToolRegistry._validate_arguments`](../../../backend/app/tools/registry.py). Tests: schema and argument cases in [`test_tools.py`](../../../backend/tests/unit/test_tools.py).

## Non-guarantees

Nested property validation, `$ref`, composition keywords, string formats/patterns, numeric ranges, and full standards compliance are not claimed. A valid payload may still be unsafe; policy, permissions, resource containment, and handler validation remain separate layers.
