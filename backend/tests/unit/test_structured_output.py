"""Validated structured-response contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel, TypeAdapter

from app.runtime.structured_output import ResponseContract, StructuredOutputError


class Answer(BaseModel):
    answer: str


class MutableInt(int):
    pass


class MutableStr(str):
    pass


@pytest.mark.unit
def test_response_contract_parses_and_validates_model() -> None:
    contract = ResponseContract(
        "answer", "1", {"type": "object", "required": ["answer"]}, Answer.model_validate
    )

    result = contract.parse_and_validate('{"answer": "yes"}')

    assert result == Answer(answer="yes")


@pytest.mark.unit
def test_response_contract_supports_type_adapter_callable() -> None:
    adapter = TypeAdapter(list[int])
    contract = ResponseContract("numbers", "1", {"type": "array"}, adapter.validate_python)

    assert contract.parse_and_validate("[1, 2]") == [1, 2]


@pytest.mark.unit
def test_malformed_json_has_typed_error_code_and_never_returns_data() -> None:
    contract = ResponseContract("answer", "1", {}, lambda value: value)

    with pytest.raises(StructuredOutputError) as raised:
        contract.parse_and_validate("not-json")

    assert raised.value.code == "malformed_json"


@pytest.mark.unit
def test_schema_validation_exception_has_typed_error_code() -> None:
    contract = ResponseContract("answer", "1", {}, Answer.model_validate)

    with pytest.raises(StructuredOutputError) as raised:
        contract.parse_and_validate('{"wrong": true}')

    assert raised.value.code == "schema_mismatch"


@pytest.mark.unit
@pytest.mark.parametrize("field", ["schema_id", "schema_version"])
def test_contract_identifiers_must_be_nonblank(field: str) -> None:
    kwargs = {"schema_id": "answer", "schema_version": "1"}
    kwargs[field] = "  "

    with pytest.raises(ValueError):
        ResponseContract(json_schema={}, validator=lambda value: value, **kwargs)


@pytest.mark.unit
@pytest.mark.parametrize("value", [bytearray(b"mutable"), {"not-json"}])
def test_schema_rejects_mutable_or_non_json_leaf_values(value: object) -> None:
    with pytest.raises(TypeError, match="unsupported value type"):
        ResponseContract("answer", "1", {"value": value}, lambda item: item)


@pytest.mark.unit
def test_schema_rejects_mutable_scalar_subclasses() -> None:
    mutable_int = MutableInt(1)
    mutable_int.notes = []  # type: ignore[attr-defined]
    mutable_key = MutableStr("value")
    mutable_key.notes = []  # type: ignore[attr-defined]

    with pytest.raises(TypeError, match="unsupported value type"):
        ResponseContract("answer", "1", {"value": mutable_int}, lambda item: item)
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        ResponseContract("answer", "1", {mutable_key: "safe"}, lambda item: item)


@pytest.mark.unit
def test_schema_rejects_cycles() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(TypeError, match="cycles"):
        ResponseContract("answer", "1", cyclic, lambda item: item)


@pytest.mark.unit
@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_non_standard_json_constants_are_malformed(text: str) -> None:
    contract = ResponseContract("answer", "1", {}, lambda value: value)

    with pytest.raises(StructuredOutputError) as raised:
        contract.parse_and_validate(text)

    assert raised.value.code == "malformed_json"


@pytest.mark.unit
def test_contract_and_schema_are_immutable_detached_copies() -> None:
    source = {"properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    contract = ResponseContract("answer", "1", source, lambda value: value)
    source["properties"]["answer"]["type"] = "number"
    source["required"].append("other")

    assert contract.json_schema["properties"]["answer"]["type"] == "string"
    assert contract.json_schema["required"] == ("answer",)
    with pytest.raises(TypeError):
        contract.json_schema["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        contract.json_schema["properties"]["answer"]["type"] = "number"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        contract.schema_id = "changed"  # type: ignore[misc]
