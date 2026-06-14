from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

import requests

from utils.logging_config import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str

    # Local HTTP embedding service
    service_url: str
    model_name: str

    # Azure OpenAI-compatible embedding endpoint
    azure_base_url: Optional[str] = None
    azure_api_key: Optional[str] = None
    azure_deployment: Optional[str] = None


class EmbeddingClient:
    def __init__(self, cfg: EmbeddingConfig):
        self.cfg = cfg

    def embed_one(self, text: str, *, timeout_s: int = 15) -> List[float]:
        vectors = self.embed_many([text], timeout_s=timeout_s)
        if not vectors:
            raise RuntimeError("No embeddings returned")
        return vectors[0]

    def embed_many(self, texts: List[str], *, timeout_s: int = 15) -> List[List[float]]:
        provider = (self.cfg.provider or "local").strip().lower()
        if provider == "azure":
            return self._embed_many_azure(texts, timeout_s=timeout_s)
        return self._embed_many_local(texts, timeout_s=timeout_s)

    def _embed_many_local(self, texts: List[str], *, timeout_s: int) -> List[List[float]]:
        payload = {"model": self.cfg.model_name, "input": texts}
        resp = requests.post(self.cfg.service_url, json=payload, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return [row["embedding"] for row in data.get("data", [])]

    def _embed_many_azure(self, texts: List[str], *, timeout_s: int) -> List[List[float]]:
        if not (self.cfg.azure_base_url and self.cfg.azure_api_key and self.cfg.azure_deployment):
            raise ValueError(
                "Azure embedding config missing. Need AZURE_EMBEDDING_BASE_URL/AZURE_EMBEDDING_API_KEY/AZURE_EMBEDDING_DEPLOYMENT"
            )

        # Import lazily so minimal installs can skip openai dependency.
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Embedding provider 'azure' requires the 'openai' package. Install extras: pip install -e '.[framework]'"
            ) from exc

        client = OpenAI(base_url=self.cfg.azure_base_url, api_key=self.cfg.azure_api_key)

        result = client.embeddings.create(input=texts, model=self.cfg.azure_deployment)
        return [row.embedding for row in result.data]


def embedding_client_from_env_like_config(cfg: Any) -> EmbeddingClient:
    """Build an EmbeddingClient from any config that looks like AgentConfig.

    Expects attributes:
    - embedding_provider, embedding_service_url, embedding_model_name
    - azure_embedding_base_url, azure_embedding_api_key, azure_embedding_deployment
    """

    return EmbeddingClient(
        EmbeddingConfig(
            provider=str(getattr(cfg, "embedding_provider", "local") or "local"),
            service_url=str(getattr(cfg, "embedding_service_url", "")),
            model_name=str(getattr(cfg, "embedding_model_name", "")),
            azure_base_url=getattr(cfg, "azure_embedding_base_url", None),
            azure_api_key=getattr(cfg, "azure_embedding_api_key", None),
            azure_deployment=getattr(cfg, "azure_embedding_deployment", None),
        )
    )
