"""Contracts for the generated vendor-neutral OTel Collector pipeline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
MODULE_PATH = ROOT / "scripts" / "generate-otel-collector-config.py"
SPEC = importlib.util.spec_from_file_location("generate_otel_collector_config", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def test_logfire_and_jaeger_generate_real_fanout_without_literal_secret() -> None:
    secret = "test-write-token-never-render"
    config = generator.generate_config(
        {
            "COGENTREX_OTEL_DESTINATIONS": "jaeger,logfire",
            "LOGFIRE_TOKEN": secret,
            "LOGFIRE_BASE_URL": "https://logfire-eu.pydantic.dev",
        }
    )
    parsed = yaml.safe_load(config)

    assert parsed["service"]["pipelines"]["traces"]["exporters"] == [
        "otlp/jaeger",
        "otlphttp/logfire",
    ]
    assert parsed["exporters"]["otlp/jaeger"] == {
        "endpoint": "jaeger:4317",
        "tls": {"insecure": True},
    }
    assert parsed["exporters"]["otlphttp/logfire"]["endpoint"] == (
        "https://logfire-eu.pydantic.dev"
    )
    assert parsed["exporters"]["otlphttp/logfire"]["headers"] == {
        "Authorization": "Bearer ${env:LOGFIRE_TOKEN}"
    }
    assert secret not in config


def test_debug_is_the_safe_default() -> None:
    parsed = yaml.safe_load(generator.generate_config({}))
    assert parsed["service"]["pipelines"]["traces"]["exporters"] == ["debug"]


@pytest.mark.parametrize("value", ["unknown", "debug,unknown", "logfire,logfire", ""])
def test_invalid_destination_selection_fails_closed(value: str) -> None:
    with pytest.raises(ValueError, match="destination"):
        generator.generate_config({"COGENTREX_OTEL_DESTINATIONS": value})


def test_selected_destination_requires_credential_but_unselected_does_not() -> None:
    generator.generate_config({"COGENTREX_OTEL_DESTINATIONS": "jaeger"})
    with pytest.raises(ValueError, match="LOGFIRE_TOKEN"):
        generator.generate_config(
            {
                "COGENTREX_OTEL_DESTINATIONS": "logfire",
                "LOGFIRE_BASE_URL": "https://logfire-eu.pydantic.dev",
            }
        )


def test_azure_tempo_and_generic_otlp_are_allowlisted() -> None:
    azure = yaml.safe_load(
        generator.generate_config(
            {
                "COGENTREX_OTEL_DESTINATIONS": "azure-monitor",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "InstrumentationKey=test",
            }
        )
    )
    assert azure["service"]["pipelines"]["traces"]["exporters"] == ["azuremonitor"]
    assert azure["exporters"]["azuremonitor"]["connection_string"] == (
        "${env:APPLICATIONINSIGHTS_CONNECTION_STRING}"
    )

    tempo = yaml.safe_load(
        generator.generate_config(
            {
                "COGENTREX_OTEL_DESTINATIONS": "tempo",
                "TEMPO_OTLP_ENDPOINT": "tempo:4317",
                "TEMPO_OTLP_INSECURE": "true",
            }
        )
    )
    assert tempo["exporters"]["otlp/tempo"]["endpoint"] == "tempo:4317"

    generic = yaml.safe_load(
        generator.generate_config(
            {
                "COGENTREX_OTEL_DESTINATIONS": "otlp",
                "COGENTREX_OTEL_GENERIC_ENDPOINT": "otel.example.test:4317",
            }
        )
    )
    assert generic["exporters"]["otlp/generic"]["endpoint"] == ("otel.example.test:4317")
    assert generic["exporters"]["otlp/generic"]["tls"] == {"insecure": False}
