"""Backend abstraction for Mem0 Platform and OSS modes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import closing, suppress
from typing import Any


def _add_kwargs(user_id: str, agent_id: str, infer: bool, metadata: dict | None) -> dict[str, Any]:
    return {"user_id": user_id, "agent_id": agent_id, "infer": infer, **({"metadata": metadata} if metadata else {})}


def _unwrap_results(response: Any) -> list:
    """Normalize API response — extract results list from dict or pass through."""
    return response.get("results", []) if isinstance(response, dict) else response if isinstance(response, list) else []


class Mem0Backend(ABC):
    """Unified interface over Platform (MemoryClient), self-hosted (HTTP) and OSS (Memory) backends.
    update()/delete() are template methods: subclasses implement raw ``_update``/``_delete``."""

    @abstractmethod
    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]: ...
    @abstractmethod
    def add(self, messages: list, *, user_id: str, agent_id: str, infer: bool = False, metadata: dict | None = None) -> dict: ...
    @abstractmethod
    def _update(self, memory_id: str, text: str) -> None: ...
    @abstractmethod
    def _delete(self, memory_id: str) -> None: ...

    def update(self, memory_id: str, text: str) -> dict:
        self._update(memory_id, text)
        return {"result": "Memory updated.", "memory_id": memory_id}

    def delete(self, memory_id: str) -> dict:
        self._delete(memory_id)
        return {"result": "Memory deleted.", "memory_id": memory_id}

    def close(self) -> None:
        pass


class PlatformBackend(Mem0Backend):
    """Wraps mem0.MemoryClient for Mem0 Platform (cloud API)."""

    def __init__(self, api_key: str):
        from mem0 import MemoryClient
        self._client = MemoryClient(api_key=api_key)

    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        return _unwrap_results(self._client.search(query, filters=filters, top_k=top_k, rerank=rerank))

    def add(self, messages: list, *, user_id: str, agent_id: str, infer: bool = False, metadata: dict | None = None) -> dict:
        return self._client.add(messages, **_add_kwargs(user_id, agent_id, infer, metadata))

    def _update(self, memory_id: str, text: str) -> None:
        self._client.update(memory_id=memory_id, text=text)

    def _delete(self, memory_id: str) -> None:
        self._client.delete(memory_id=memory_id)


class SelfHostedBackend(Mem0Backend):
    """Direct HTTP backend for a self-hosted Mem0 server (the FastAPI ``server/``).
    mem0.MemoryClient is hardwired to the cloud API (``Authorization: Token``, ``GET /v1/ping/`` in ``__init__``),
    so this speaks the server's real contract: ``X-API-Key`` auth and the ``/memories`` / ``/search`` routes."""

    def __init__(self, api_key: str, host: str, transport=None, *, settings=None):
        import httpx
        self._settings = settings or {}
        self._journal = None
        if self._settings.get("durable_writes", False):
            from hermes_constants import get_hermes_home
            from ._delivery import DeliveryJournal
            self._journal = DeliveryJournal(get_hermes_home() / "mem0-delivery.db", int(self._settings.get("max_pending_writes", 100)))
        headers = {"Content-Type": "application/json", **({"X-API-Key": api_key} if api_key else {})}  # key omitted only for AUTH_DISABLED servers
        # No transport retries: a write's ambiguous outcome must be reconciled first.
        self._client = httpx.Client(base_url=host.rstrip("/"), headers=headers, timeout=httpx.Timeout(float(self._settings.get("write_timeout_seconds", 30)), connect=5), transport=transport or httpx.HTTPTransport(retries=0))

    def _json(self, method: str, path: str, **kwargs) -> Any:
        resp = self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        # rerank is platform-only; the self-hosted /search ignores it. user_id belongs in filters (top-level is deprecated).
        return _unwrap_results(self._json("POST", "/search", timeout=float(self._settings.get("search_timeout_seconds", 10)), json={"query": query, "top_k": top_k, "show_expired": False, **({"filters": filters} if filters else {})}))

    def add(self, messages: list, *, user_id: str, agent_id: str, infer: bool = False, metadata: dict | None = None) -> dict:
        payload = {"messages": messages, **_add_kwargs(user_id, agent_id, infer, metadata)}
        if self._journal is None:
            return self._json("POST", "/memories", json=payload)
        request_id = self._journal.stage(payload)
        previous = self._journal.status(request_id)
        if previous['delivery_status'] == 'confirmed' and not infer:
            receipts = previous.get('results', [])
            current = [self._json('GET', f"/memories/{r['id']}") for r in receipts if r.get('id')]
            if not current or any(not r or r.get('memory') != messages[0]['content'] for r in current):
                self._journal.supersede(request_id)
                request_id = self._journal.stage(payload)
        self.drain_pending()
        return self._journal.status(request_id)

    def stage_add(self, messages, *, user_id, agent_id, infer=True, metadata=None):
        return self._journal.stage({"messages": messages, **_add_kwargs(user_id, agent_id, infer, metadata)})

    def drain_pending(self, should_stop=lambda: False):
        if self._journal:
            self._journal.drain(self._send_write, should_stop)

    def _send_write(self, payload):
        operation = payload.get('operation')
        if not operation:
            return self._json('POST', '/memories', json=payload)
        path = f"/memories/{payload['memory_id']}"
        if operation == 'update':
            self._json('PUT', path, json={'text': payload['text']})
        else:
            self._json('DELETE', path)
        receipt = self._check_mutation(payload)
        if receipt is None:
            raise ValueError('Mutation read-back did not confirm the requested state')
        return receipt

    def _check_mutation(self, payload):
        import httpx
        try:
            current = self._json('GET', f"/memories/{payload['memory_id']}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            current = None
        matches = (not current) if payload['operation'] == 'delete' else (
            current and current.get('memory') == payload['text'])
        if matches:
            return {'results': [{'id': payload['memory_id']}], 'result': 'Requested state verified by read-back.'}
        return None

    def _mutate(self, operation, memory_id, text=None):
        payload = {'operation': operation, 'memory_id': memory_id}
        if text is not None:
            payload['text'] = text
        request_id = self._journal.stage(payload)
        if self._journal.status(request_id)['delivery_status'] == 'confirmed' and self._check_mutation(payload) is None:
            self._journal.supersede(request_id)
            request_id = self._journal.stage(payload)
        self.drain_pending()
        result = self._journal.status(request_id)
        if result['delivery_status'] != 'confirmed':
            result['result'] = 'Mutation pending confirmation. Do not claim completion or resubmit.'
        return result

    def update(self, memory_id, text):
        return self._mutate('update', memory_id, text) if self._journal else super().update(memory_id, text)

    def delete(self, memory_id):
        return self._mutate('delete', memory_id) if self._journal else super().delete(memory_id)

    def reconcile_pending(self):
        if self._journal:
            self._journal.reconcile(lambda user: _unwrap_results(self._json(
                "GET", "/memories", params={"user_id": user, "top_k": 1000, "show_expired": "true"})), self._check_mutation)

    def update_metadata(self, memory_id, *, metadata=None, expiration_date=None):
        return self._json("PUT", f"/memories/{memory_id}", json={
            "metadata": metadata or {}, "expiration_date": expiration_date})

    def _update(self, memory_id: str, text: str) -> None:
        self._json("PUT", f"/memories/{memory_id}", json={"text": text})

    def _delete(self, memory_id: str) -> None:
        self._json("DELETE", f"/memories/{memory_id}")

    def close(self) -> None:
        with suppress(Exception):
            self._client.close()


_DIRECT_OPENAI_PROVIDER = "hermes_openai"
_DIRECT_OPENAI_CLASS_PATH = "plugins.memory.mem0._openai_llm.DirectOpenAILLM"


def _register_direct_openai_provider() -> None:
    """Register Hermes' OpenAI-only Mem0 LLM provider once per factory."""
    from mem0.configs.llms.openai import OpenAIConfig
    from mem0.utils.factory import LlmFactory
    provider_map = getattr(LlmFactory, "provider_to_class", None)
    register_provider = getattr(LlmFactory, "register_provider", None)
    if not isinstance(provider_map, dict) or not callable(register_provider):
        raise RuntimeError("mem0 LlmFactory does not support the provider registration required for the Hermes OpenAI OSS backend")
    if provider_map.get(_DIRECT_OPENAI_PROVIDER) != (_DIRECT_OPENAI_CLASS_PATH, OpenAIConfig):
        register_provider(_DIRECT_OPENAI_PROVIDER, _DIRECT_OPENAI_CLASS_PATH, OpenAIConfig)


class OSSBackend(Mem0Backend):
    """Wraps mem0.Memory for self-hosted (OSS) mode."""

    def __init__(self, oss_config: dict):
        import os
        from mem0 import Memory
        from ._oss_providers import EMBEDDER_PROVIDERS, KNOWN_DIMS, LLM_PROVIDERS

        def _provider_block(name: str, registry: dict) -> dict:
            """Copy of oss_config[name] with the legacy ``api_base`` key mapped to the provider's canonical base-URL key."""
            block = dict(oss_config[name])
            provider_config = dict(block.get("config", {}))
            legacy_base = provider_config.pop("api_base", None)
            canonical_key = registry.get(str(block.get("provider") or "").strip().lower(), {}).get("base_url_key")
            if legacy_base and canonical_key:
                provider_config.setdefault(canonical_key, legacy_base)
            block["config"] = provider_config
            return block

        vector_store = dict(oss_config["vector_store"])
        vs_config = dict(vector_store.get("config", {}))
        if "path" in vs_config:
            vs_config["path"] = os.path.expanduser(vs_config["path"])
        embedder_config = oss_config.get("embedder", {}).get("config", {})
        dims = embedder_config.get("embedding_dims") or KNOWN_DIMS.get(embedder_config.get("model", ""))
        if dims:
            vs_config["embedding_model_dims"] = dims
            self._recreate_collection_if_dims_changed(vector_store.get("provider", "qdrant"), vs_config, dims)
        vector_store["config"] = vs_config
        config = {"vector_store": vector_store, "llm": _provider_block("llm", LLM_PROVIDERS), "embedder": _provider_block("embedder", EMBEDDER_PROVIDERS), "version": "v1.1"}
        if str(config["llm"].get("provider") or "").strip().lower() == "openai":
            # mem0 validates LlmConfig.provider before its factory lookup: build the supported OpenAI config, then swap the provider.
            _register_direct_openai_provider()
            from mem0.configs.base import MemoryConfig
            memory_config = MemoryConfig(**config)
            try:
                memory_config.llm.provider = _DIRECT_OPENAI_PROVIDER
            except (AttributeError, TypeError) as exc:
                raise RuntimeError("mem0 MemoryConfig does not expose a mutable llm.provider for the Hermes OpenAI OSS backend") from exc
            self._memory = Memory(memory_config)
        else:
            self._memory = Memory.from_config(config)

    @staticmethod
    def _recreate_collection_if_dims_changed(provider: str, vs_config: dict, expected_dims: int) -> None:
        """Delete stale vector collection when embedding dimensions change."""
        collection_name = vs_config.get("collection_name", "mem0")
        with suppress(Exception):
            if provider == "qdrant":
                from qdrant_client import QdrantClient
                path, url = vs_config.get("path"), vs_config.get("url")
                if path:
                    client = QdrantClient(path=path)
                elif url:
                    client = QdrantClient(url=url, api_key=vs_config.get("api_key"))
                else:
                    return
                with closing(client):
                    if not client.collection_exists(collection_name):
                        return
                    vectors = client.get_collection(collection_name).config.params.vectors
                    # Named-vector collections expose a dict; unnamed expose an object with .size.
                    if isinstance(vectors, dict):
                        vectors = next(iter(vectors.values()), None)
                    current_dims = getattr(vectors, "size", None)
                    if current_dims is not None and current_dims != expected_dims:
                        client.delete_collection(collection_name)
            elif provider == "pgvector":
                import psycopg2
                from psycopg2 import sql as pgsql
                conn_params = {k: vs_config[k] for k in ("host", "port", "user", "password", "dbname", "sslmode") if vs_config.get(k)}
                with closing(psycopg2.connect(**conn_params)) as conn:
                    conn.autocommit = True
                    with closing(conn.cursor()) as cur:
                        cur.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'vector'", (collection_name,))
                        row = cur.fetchone()
                        if row and row[0] > 0 and row[0] != expected_dims:
                            cur.execute(pgsql.SQL("DROP TABLE IF EXISTS {}").format(pgsql.Identifier(collection_name)))

    def search(self, query: str, *, filters: dict, top_k: int = 10, rerank: bool = False) -> list[dict]:
        return _unwrap_results(self._memory.search(query, filters=filters, top_k=top_k))

    def add(self, messages: list, *, user_id: str, agent_id: str, infer: bool = False, metadata: dict | None = None) -> dict:
        return self._memory.add(messages, **_add_kwargs(user_id, agent_id, infer, metadata))

    def _update(self, memory_id: str, text: str) -> None:
        self._memory.update(memory_id, data=text)

    def _delete(self, memory_id: str) -> None:
        self._memory.delete(memory_id)

    def close(self):
        with suppress(Exception):
            telemetry = getattr(self._memory, "telemetry", None)
            if telemetry and hasattr(telemetry, "posthog"):
                with suppress(Exception):
                    telemetry.posthog.shutdown()
            vs = getattr(self._memory, "vector_store", None)
            # Memory, then its vector store, then the store's raw client; the first failure aborts the chain.
            for obj in filter(None, (self._memory, vs, getattr(vs, "client", None))):
                if hasattr(obj, "close"):
                    obj.close()
