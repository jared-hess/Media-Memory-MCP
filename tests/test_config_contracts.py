from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Literal

import pytest

from media_memory import config as config_module
from media_memory.config import EmbeddingsConfig, IndexConfig, MediaMemoryConfig, MetadataConfig, SearchConfig, load_config
from media_memory.core.embeddings import MockEmbeddingProvider
from media_memory.mcp_server import tools as mcp_tools

cli_main = importlib.import_module("media_memory.cli.main")


ProofType = Literal["constructor", "external-client call", "service behavior", "fail-fast", "reserved"]
ContractStatus = Literal["implemented", "fail-fast", "reserved/documented", "drift-risk"]
RuntimeBoundary = Literal[
    "pydantic config",
    "provider factory",
    "external provider client",
    "index service",
    "search service",
    "metadata service",
    "mcp tool registration",
    "cli status",
]

ALLOWED_PROOF_TYPES = {
    "constructor",
    "external-client call",
    "service behavior",
    "fail-fast",
    "reserved",
}
ALLOWED_STATUSES = {"implemented", "fail-fast", "reserved/documented", "drift-risk"}
ALLOWED_RUNTIME_BOUNDARIES = {
    "pydantic config",
    "provider factory",
    "external provider client",
    "index service",
    "search service",
    "metadata service",
    "mcp tool registration",
    "cli status",
}

REQUIRED_FIELDS = {
    "field",
    "proof_type",
    "status",
    "runtime_boundary",
    "verification_strategy",
}
CRITICAL_CONFIG_FIELDS = {
    "embeddings.provider",
    "embeddings.model",
    "embeddings.batch_size",
    "embeddings.api_key",
    "embeddings.dimensions",
    "index.vector_db",
    "index.vector_path",
    "search.lexical_weight",
    "search.vector_weight",
    "search.metadata_boost_weight",
    "metadata.fetch_external",
    "metadata.prefer",
    "mcp.allow_ingest_tools",
    "media_sources.filesystem.enabled",
    "media_sources.plex.enabled",
    "subtitle_sources.local.enabled",
    "subtitle_sources.embedded.enabled",
    "subtitle_sources.opensubtitles.enabled",
    "subtitle_sources.bazarr.enabled",
}


@dataclass(frozen=True)
class ConfigContractRow:
    field: str
    proof_type: ProofType
    status: ContractStatus
    runtime_boundary: RuntimeBoundary
    verification_strategy: str


CONFIG_CONTRACT_MATRIX: tuple[ConfigContractRow, ...] = (
    ConfigContractRow(
        field="embeddings.provider",
        proof_type="constructor",
        status="implemented",
        runtime_boundary="provider factory",
        verification_strategy="Assert mock builds locally and OpenAI path is selected only when configured.",
    ),
    ConfigContractRow(
        field="embeddings.model",
        proof_type="external-client call",
        status="implemented",
        runtime_boundary="external provider client",
        verification_strategy="Provider constructor accepts/configurable model, forwards it to embeddings.create, and CLI/MCP factories pass config.embeddings.model to the provider constructor.",
    ),
    ConfigContractRow(
        field="embeddings.batch_size",
        proof_type="reserved",
        status="reserved/documented",
        runtime_boundary="pydantic config",
        verification_strategy="Documented config exists; future batching behavior should consume this value.",
    ),
    ConfigContractRow(
        field="embeddings.api_key",
        proof_type="fail-fast",
        status="fail-fast",
        runtime_boundary="provider factory",
        verification_strategy="OpenAI provider construction fails without a configured key and reads no live env secret.",
    ),
    ConfigContractRow(
        field="embeddings.dimensions",
        proof_type="constructor",
        status="implemented",
        runtime_boundary="provider factory",
        verification_strategy="Assert mock/OpenAI provider constructors receive configured dimensions.",
    ),
    ConfigContractRow(
        field="index.vector_db",
        proof_type="fail-fast",
        status="fail-fast",
        runtime_boundary="index service",
        verification_strategy="Assert unsupported vector_db values fail fast before runtime silently builds LanceDB.",
    ),
    ConfigContractRow(
        field="index.vector_path",
        proof_type="constructor",
        status="implemented",
        runtime_boundary="index service",
        verification_strategy="Assert Lance vector store uses the configured path for local index files.",
    ),
    ConfigContractRow(
        field="search.lexical_weight",
        proof_type="fail-fast",
        status="fail-fast",
        runtime_boundary="search service",
        verification_strategy="Assert non-default lexical weights fail fast until ranking consumes configured weights.",
    ),
    ConfigContractRow(
        field="search.vector_weight",
        proof_type="fail-fast",
        status="fail-fast",
        runtime_boundary="search service",
        verification_strategy="Assert non-default vector weights fail fast until ranking consumes configured weights.",
    ),
    ConfigContractRow(
        field="search.metadata_boost_weight",
        proof_type="fail-fast",
        status="fail-fast",
        runtime_boundary="search service",
        verification_strategy="Assert non-default metadata boost weights fail fast until ranking consumes configured weights.",
    ),
    ConfigContractRow(
        field="metadata.fetch_external",
        proof_type="fail-fast",
        status="fail-fast",
        runtime_boundary="metadata service",
        verification_strategy="Assert fetch_external=true fails fast until external metadata source selection exists.",
    ),
    ConfigContractRow(
        field="metadata.prefer",
        proof_type="service behavior",
        status="reserved/documented",
        runtime_boundary="metadata service",
        verification_strategy="Assert preference order is exposed in status; later metadata resolver should consume it.",
    ),
    ConfigContractRow(
        field="mcp.allow_ingest_tools",
        proof_type="service behavior",
        status="implemented",
        runtime_boundary="mcp tool registration",
        verification_strategy="Assert ingest tools are hidden by default and registered only when explicitly enabled.",
    ),
    ConfigContractRow(
        field="media_sources.filesystem.enabled",
        proof_type="service behavior",
        status="implemented",
        runtime_boundary="cli status",
        verification_strategy="Assert provider status reports filesystem enablement from configured media sources.",
    ),
    ConfigContractRow(
        field="media_sources.plex.enabled",
        proof_type="reserved",
        status="reserved/documented",
        runtime_boundary="cli status",
        verification_strategy="Assert Plex remains disabled by default and visible as an explicit provider gate.",
    ),
    ConfigContractRow(
        field="subtitle_sources.local.enabled",
        proof_type="service behavior",
        status="implemented",
        runtime_boundary="cli status",
        verification_strategy="Assert status reports the local sidecar subtitle provider gate.",
    ),
    ConfigContractRow(
        field="subtitle_sources.embedded.enabled",
        proof_type="reserved",
        status="reserved/documented",
        runtime_boundary="cli status",
        verification_strategy="Assert embedded subtitles remain disabled by default and visible as a provider gate.",
    ),
    ConfigContractRow(
        field="subtitle_sources.opensubtitles.enabled",
        proof_type="reserved",
        status="reserved/documented",
        runtime_boundary="cli status",
        verification_strategy="Assert OpenSubtitles remains disabled by default and visible as a provider gate.",
    ),
    ConfigContractRow(
        field="subtitle_sources.bazarr.enabled",
        proof_type="reserved",
        status="reserved/documented",
        runtime_boundary="cli status",
        verification_strategy="Assert Bazarr remains disabled by default and visible as a provider gate.",
    ),
)


def test_config_contract_matrix_rows_have_required_metadata() -> None:
    for row in CONFIG_CONTRACT_MATRIX:
        payload = row.__dict__
        assert set(payload) == REQUIRED_FIELDS
        assert row.field
        assert row.proof_type in ALLOWED_PROOF_TYPES
        assert row.status in ALLOWED_STATUSES
        assert row.runtime_boundary in ALLOWED_RUNTIME_BOUNDARIES
        assert row.verification_strategy.strip()


def test_config_contract_matrix_covers_critical_fields() -> None:
    matrix_fields = {row.field for row in CONFIG_CONTRACT_MATRIX}

    assert CRITICAL_CONFIG_FIELDS <= matrix_fields


def test_config_contract_matrix_has_unique_fields() -> None:
    matrix_fields = [row.field for row in CONFIG_CONTRACT_MATRIX]

    assert len(matrix_fields) == len(set(matrix_fields))


class _FakeOpenAIEmbeddingProvider:
    calls: list[dict[str, object]] = []

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        dimensions: int | None = None,
    ) -> None:
        self.calls.append(
            {"api_key": api_key, "model": model, "dimensions": dimensions}
        )


def _sentinel_openai_config() -> MediaMemoryConfig:
    return MediaMemoryConfig(
        embeddings=EmbeddingsConfig(
            provider="openai",
            model="sentinel-openai-model",
            api_key="sentinel-api-key",
            dimensions=123,
        )
    )


def _validate_runtime_config(config: MediaMemoryConfig) -> None:
    validator = getattr(config_module, "validate_supported_runtime_config", lambda config: None)
    validator(config)


def test_cli_openai_embedding_factory_receives_configured_values(monkeypatch) -> None:
    _FakeOpenAIEmbeddingProvider.calls = []
    monkeypatch.setattr(cli_main, "OpenAIEmbeddingProvider", _FakeOpenAIEmbeddingProvider)

    provider = cli_main._build_embeddings(_sentinel_openai_config())

    assert isinstance(provider, _FakeOpenAIEmbeddingProvider)
    assert _FakeOpenAIEmbeddingProvider.calls == [
        {
            "api_key": "sentinel-api-key",
            "model": "sentinel-openai-model",
            "dimensions": 123,
        }
    ]


def test_mcp_openai_embedding_factory_receives_configured_values(monkeypatch) -> None:
    _FakeOpenAIEmbeddingProvider.calls = []
    monkeypatch.setattr(mcp_tools, "OpenAIEmbeddingProvider", _FakeOpenAIEmbeddingProvider)

    provider = mcp_tools._build_embeddings(_sentinel_openai_config())

    assert isinstance(provider, _FakeOpenAIEmbeddingProvider)
    assert _FakeOpenAIEmbeddingProvider.calls == [
        {
            "api_key": "sentinel-api-key",
            "model": "sentinel-openai-model",
            "dimensions": 123,
        }
    ]


def test_embedding_factories_preserve_mock_provider_dimensions() -> None:
    config = MediaMemoryConfig(
        embeddings=EmbeddingsConfig(provider="mock", dimensions=123)
    )

    cli_provider = cli_main._build_embeddings(config)
    mcp_provider = mcp_tools._build_embeddings(config)

    assert isinstance(cli_provider, MockEmbeddingProvider)
    assert isinstance(mcp_provider, MockEmbeddingProvider)
    assert cli_provider.dims == 123
    assert mcp_provider.dims == 123


def test_default_runtime_config_passes_supported_runtime_validation() -> None:
    _validate_runtime_config(MediaMemoryConfig())


def test_runtime_validation_rejects_unsupported_vector_db() -> None:
    config = MediaMemoryConfig(index=IndexConfig(vector_db="memory"))

    with pytest.raises(ValueError, match="index\\.vector_db.*memory"):
        _validate_runtime_config(config)


@pytest.mark.parametrize(
    ("field_name", "search_config", "value"),
    [
        ("search.lexical_weight", SearchConfig(lexical_weight=0.25), "0.25"),
        ("search.vector_weight", SearchConfig(vector_weight=0.25), "0.25"),
        (
            "search.metadata_boost_weight",
            SearchConfig(metadata_boost_weight=0.25),
            "0.25",
        ),
    ],
)
def test_runtime_validation_rejects_non_default_search_weights(
    field_name: str,
    search_config: SearchConfig,
    value: str,
) -> None:
    config = MediaMemoryConfig(search=search_config)

    with pytest.raises(ValueError, match=f"{field_name}.*{value}"):
        _validate_runtime_config(config)


def test_runtime_validation_rejects_external_metadata_fetch() -> None:
    config = MediaMemoryConfig(metadata=MetadataConfig(fetch_external=True))

    with pytest.raises(ValueError, match="metadata\\.fetch_external.*True"):
        _validate_runtime_config(config)


def test_metadata_prefer_defaults_remain_valid_when_external_fetch_disabled() -> None:
    config = MediaMemoryConfig(metadata=MetadataConfig(prefer=["plex", "tmdb", "tvmaze"]))

    _validate_runtime_config(config)


def test_load_config_rejects_unsupported_vector_db(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
index:
  vector_db: disabled
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="index\\.vector_db.*disabled"):
        load_config(config_path)
