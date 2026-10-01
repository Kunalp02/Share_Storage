from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from agent_execution.api.request_context import client_address
from agent_execution.agents.graph.builder import build_execution_graph
from agent_execution.agents.graph.context import AgentGraphContext
from agent_execution.agents.graph.nodes import AgentGraphNodes
from agent_execution.agents.graph.routing import route_after_llm
from agent_execution.infrastructure.platform.rag_ask_client import RagAskClient
from agent_execution.services.manifest_service import RagContextService
from agent_execution.core.exceptions import ServiceError
from agent_execution.infrastructure.conversation_store.session_key import ConversationSessionKey
from agent_execution.schemas.runs import CreateDeploymentRequest, RunStatus
from agent_execution.schemas.runtime import (
    AgentMemoryScope,
    KnowledgeBaseMode,
    KnowledgeBaseRef,
    MemoryConfig,
    ModelConfig,
    RuntimeManifest,
)
from agent_execution.schemas.threads import Channel, CreateThreadRequest, ExecutionType
from agent_execution.services.conversation_memory_service import ConversationMemoryService
from agent_execution.services.conversation_models import ConversationHistory, ConversationTurn, MemoryContext
from agent_execution.services.context_manager import ContextManager
from agent_execution.services.deployment_service import DeploymentService, hash_api_key
from agent_execution.services.key_crypto import decrypt_key, encrypt_key
from agent_execution.services.prompt_composition_service import PromptCompositionService
from agent_execution.services.run_policy import describe_failure, pins_manifest, retry_delay_seconds, status_after_failure
from agent_execution.services.thread_service import ThreadService
from agent_execution.infrastructure.conversation_store.memory_store import InMemoryConversationHistoryStore


def _manifest(**kwargs) -> RuntimeManifest:
    manifest = RuntimeManifest(
        agent_id=uuid4(),
        name="Test Agent",
        status="Draft",
        system_prompt="You are helpful.",
        model=ModelConfig(model_id=uuid4(), model_identifier="gpt-4o-mini"),
        memory=MemoryConfig(enabled=True, scope=AgentMemoryScope.SESSION),
    )
    for key, value in kwargs.items():
        setattr(manifest, key, value)
    return manifest


def test_memory_service_requires_session():
    settings = SimpleNamespace(conversation_max_turn_pairs=10, conversation_max_chars=8000, memory_cache_ttl_seconds=30)
    service = ConversationMemoryService(settings, InMemoryConversationHistoryStore())
    with pytest.raises(ServiceError) as exc:
        service.validate_context(
            MemoryConfig(enabled=True, scope=AgentMemoryScope.SESSION),
            MemoryContext(session_id=None),
        )
    assert exc.value.code == "MEMORY_CONTEXT_REQUIRED"


def test_history_trim_respects_turn_pairs_and_chars():
    history = ConversationHistory(turns=[ConversationTurn("user", "x" * 50) for _ in range(8)])
    trimmed, truncated = history.trim(max_turn_pairs=2, max_chars=100_000)
    assert len(trimmed.turns) == 4
    assert truncated is True
    trimmed, truncated = history.trim(max_turn_pairs=10, max_chars=60)
    assert truncated is True
    assert sum(len(turn.content) for turn in trimmed.turns) <= 60


def test_route_after_llm():
    assert route_after_llm({"has_tools": False}) == "persist_memory"
    assert route_after_llm({"has_tools": True, "tool_calls": [], "tool_round": 0}) == "persist_memory"
    assert route_after_llm({"has_tools": True, "tool_calls": [{}], "tool_round": 1, "max_tool_rounds": 5}) == "run_tools"
    assert route_after_llm({"has_tools": True, "tool_calls": [{}], "tool_round": 5, "max_tool_rounds": 5}) == "finalize_answer"


def test_prompt_includes_files_and_knowledge():
    manifest = _manifest(
        knowledge_bases=[
            KnowledgeBaseRef(knowledge_base_id=uuid4(), knowledge_base_name="Policies", mode=KnowledgeBaseMode.CONTEXT)
        ]
    )
    prompt = PromptCompositionService.compose(
        manifest,
        "Previous conversation",
        ["KB: Policies\n[1] claim"],
        "Attached files:\n\nFile notes.txt:\nhello",
    )
    assert "Previous conversation" in prompt
    assert "Policies" in prompt
    assert "notes.txt" in prompt


def test_production_threads_pin_manifest_and_retries_requeue():
    assert pins_manifest(ExecutionType.PRODUCTION) is True
    assert pins_manifest(ExecutionType.TEST) is False
    assert status_after_failure(1, 3) == RunStatus.QUEUED
    assert status_after_failure(3, 3) == RunStatus.FAILED
    assert status_after_failure(1, 3, transient=False) == RunStatus.FAILED


def test_failure_reason_is_auditable_and_permanent_errors_do_not_retry():
    code, message, transient = describe_failure(
        ServiceError("CONTEXT_TOO_LARGE", "The system prompt and the new message are larger than the context budget.", 400)
    )
    assert code == "CONTEXT_TOO_LARGE"
    assert "context budget" in message
    assert transient is False
    code, message, transient = describe_failure(ServiceError("RAG_UNAVAILABLE", "RAG ask service is unreachable.", 503))
    assert code == "RAG_UNAVAILABLE"
    assert transient is True
    code, message, transient = describe_failure(TimeoutError())
    assert code == "TIMEOUT"
    assert "timed out" in message
    assert transient is True
    code, message, _ = describe_failure(RuntimeError("secret database password"))
    assert code == "RUN_FAILED"
    assert "password" not in message
    assert retry_delay_seconds(1, 2, 60) == 2
    assert retry_delay_seconds(3, 2, 60) == 8
    assert retry_delay_seconds(10, 2, 60) == 60


def test_api_key_hash_is_stable():
    assert hash_api_key("ak_test") == hash_api_key("ak_test")
    assert hash_api_key("ak_test") != hash_api_key("ak_other")


def test_graph_compiles():
    context = AgentGraphContext.__new__(AgentGraphContext)
    assert build_execution_graph(context) is not None


class _Repo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def insert(self, **kwargs):
        self.rows.append(kwargs)


class _Manifests:
    def __init__(self, published: bool) -> None:
        self.published = published

    async def resolve(self, agent_id, bearer_token, *, revision_id=None, published_only=False):
        if published_only and not self.published:
            raise ServiceError("AGENT_NOT_PUBLISHED", "Production execution requires a published agent.", 400)
        manifest = _manifest(status="Published" if self.published else "Draft")
        manifest.agent_id = agent_id
        return manifest


@pytest.mark.asyncio
async def test_studio_test_thread_does_not_snapshot_draft():
    repo = _Repo()
    settings = SimpleNamespace(test_thread_ttl_hours=24, default_production_retention_policy="PERMANENT")
    service = ThreadService(settings, repo, _Manifests(published=False))
    await service.create(
        uuid4(),
        CreateThreadRequest(execution_type=ExecutionType.TEST),
        channel=Channel.STUDIO,
        bearer_token="token",
        triggered_by="builder",
    )
    assert repo.rows[0]["manifest_snapshot"] is None
    assert repo.rows[0]["execution_type"] == "TEST"


def test_context_budget_drops_files_before_the_system_prompt():
    manifest = _manifest(system_prompt="Stay short.")
    prompt, traces = PromptCompositionService.compose_within_budget(
        manifest,
        "history " * 40,
        ["knowledge " * 40],
        "file " * 80,
        "hello",
        budget_chars=180,
    )
    assert "Stay short." in prompt
    assert "hello" not in prompt
    assert traces[0] == "context.trimmed:files"


def test_api_key_round_trip_and_replacement_when_unreadable():
    secret = "unit-test-secret"
    token = encrypt_key(secret, "ak_visible")
    assert decrypt_key(secret, token) == "ak_visible"
    assert decrypt_key("other-secret", token) is None


class _Deployments:
    def __init__(self, row=None) -> None:
        self.row = row
        self.rotated = None

    async def get_by_agent(self, agent_id):
        return self.row

    async def get_by_slug(self, slug):
        return None

    async def insert(self, **kwargs):
        self.row = {
            "deployment_id": kwargs["deployment_id"],
            "agent_id": kwargs["agent_id"],
            "slug": kwargs["slug"],
            "revision_id": kwargs["revision_id"],
            "api_key_hash": kwargs["api_key_hash"],
            "api_key_enc": kwargs["api_key_enc"],
            "retention_policy": kwargs["retention_policy"],
            "enabled": True,
            "created_at": None,
        }

    async def rotate_key(self, deployment_id, api_key_hash, api_key_enc):
        self.rotated = (deployment_id, api_key_hash, api_key_enc)
        self.row = {**self.row, "api_key_hash": api_key_hash, "api_key_enc": api_key_enc}

    async def list_for_agent(self, agent_id):
        return [self.row] if self.row else []


class _Settings:
    api_key_encryption_secret = "unit-test-secret"
    public_base_url = "https://runtime.example"
    conversation_max_turn_pairs = 10
    conversation_max_chars = 8000
    memory_cache_ttl_seconds = 30
    persist_conversation_memory = True

    @staticmethod
    def context_input_budget_chars() -> int:
        return 500


@pytest.mark.asyncio
async def test_existing_deployment_without_a_stored_key_reissues_one():
    agent_id = uuid4()
    repo = _Deployments(
        {
            "deployment_id": uuid4(),
            "agent_id": agent_id,
            "slug": "claims",
            "revision_id": None,
            "retention_policy": "PERMANENT",
            "enabled": True,
            "created_at": None,
            "api_key_enc": None,
        }
    )
    service = DeploymentService(repo, _Manifests(published=True), _Settings())
    created = await service.create(agent_id, CreateDeploymentRequest(), "token", "http://localhost/")
    assert created.api_key.startswith("ak_")
    assert created.key_reissued is True
    assert created.chat_url == f"https://runtime.example/api/v1/agents/{agent_id}/chat"
    assert decrypt_key(_Settings.api_key_encryption_secret, repo.row["api_key_enc"]) == created.api_key


@pytest.mark.asyncio
async def test_context_manager_keeps_memory_on_the_thread_expiry():
    store = InMemoryConversationHistoryStore()
    settings = _Settings()
    memory = ConversationMemoryService(settings, store)
    manager = ContextManager(settings, memory, store, _Rag(), _Storage())
    manifest = _manifest()
    thread_id = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    thread = {"thread_id": thread_id, "expires_at": expires, "retention_policy": "TEMPORARY"}
    prepared = await manager.prepare(
        manifest=manifest,
        thread=thread,
        user_input="hello",
        artifact_ids=[],
        bearer_token=None,
    )
    assert "You are helpful." in prepared.system_prompt
    saved = await manager.remember(manifest=manifest, thread=thread, user_input="hello", assistant_text="hi")
    assert saved is True
    key = ConversationSessionKey(manifest.agent_id, str(thread_id), "")
    loaded, _ = await store.get_history(key)
    assert loaded.turns[-1].content == "hi"
    store._sessions[f"{manifest.agent_id}:{thread_id}:"].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired, _ = await store.get_history(key)
    assert expired.turns == []


class _Rag:
    async def fetch_context(self, manifest, user_input, bearer_token):
        return [], []


class _Storage:
    async def fetch_artifact_text(self, artifact_id):
        return {"filename": "a.txt", "text": "", "truncated": False}


@pytest.mark.asyncio
async def test_production_thread_rejects_unpublished_agent():
    service = ThreadService(
        SimpleNamespace(test_thread_ttl_hours=24, default_production_retention_policy="PERMANENT"),
        _Repo(),
        _Manifests(published=False),
    )
    with pytest.raises(ServiceError) as exc:
        await service.create(
            uuid4(),
            CreateThreadRequest(execution_type=ExecutionType.PRODUCTION),
            channel=Channel.STUDIO,
            bearer_token="token",
            triggered_by="builder",
        )
    assert exc.value.code == "AGENT_NOT_PUBLISHED"


def test_client_address_uses_the_first_forwarded_hop():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "10.4.4.4, 172.16.0.1", "x-real-ip": "172.16.0.1"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_address(request) == "10.4.4.4"
    direct = SimpleNamespace(headers={}, client=SimpleNamespace(host="192.168.1.20"))
    assert client_address(direct) == "192.168.1.20"


@pytest.mark.asyncio
async def test_rag_ask_connection_failure_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rag.test") as http:
        client = RagAskClient(http)
        with pytest.raises(ServiceError) as exc:
            await client.ask(uuid4(), "what is the policy", "token")
    assert exc.value.code == "RAG_UNAVAILABLE"
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_context_kb_outage_asks_the_model_and_records_a_trace():
    kb_id = uuid4()

    class _RagAsk:
        async def ask(self, knowledge_base_id, question, bearer_token):
            raise ServiceError("RAG_UNAVAILABLE", "RAG ask service is unreachable.", 503)

    manifest = _manifest(
        knowledge_bases=[
            KnowledgeBaseRef(knowledge_base_id=kb_id, knowledge_base_name="Policies", mode=KnowledgeBaseMode.CONTEXT)
        ]
    )
    blocks, raw = await RagContextService(SimpleNamespace(rag_ask=_RagAsk())).fetch_context(
        manifest, "what is the policy", "token"
    )
    assert "something went wrong" in blocks[0]
    assert "Do not invent sources." in blocks[0]
    assert raw[0]["trace"] == "rag.unavailable:Policies:RAG_UNAVAILABLE"
    assert raw[0]["code"] == "RAG_UNAVAILABLE"


@pytest.mark.asyncio
async def test_tool_outage_returns_a_user_message_for_the_model():
    class _Tools:
        async def run(self, manifest, name, args, bearer_token, user_input):
            raise ServiceError("RAG_UNAVAILABLE", "RAG ask service is unreachable.", 503)

    nodes = AgentGraphNodes(SimpleNamespace(tool_service=_Tools()))
    manifest = _manifest()
    state = {
        "manifest": manifest.model_dump(mode="json"),
        "messages": [{"role": "user", "content": "what is the policy"}],
        "user_input": "what is the policy",
        "tool_round": 0,
        "tool_calls": [{"id": "call_1", "name": "rag_ask", "arguments": {"question": "policy"}}],
        "tool_results": [],
        "bearer_token": "token",
    }
    update = await nodes.run_tools(state)
    assert update["steps"] == ["run_tools:r1", "tool.failed:rag_ask:RAG_UNAVAILABLE"]
    payload = json.loads(update["tool_results"][0]["output"])
    assert payload["status"] == "unavailable"
    assert "Something went wrong" in payload["tell_user"]
    assert update["messages"][-1]["role"] == "tool"


def test_prompt_budget_drops_knowledge_before_the_system_prompt():
    manifest = _manifest(system_prompt="Stay helpful.")
    prompt, traces = PromptCompositionService.compose_within_budget(
        manifest,
        "Previous conversation (most recent last):\nUser: old fact",
        ["KB: Policies\n" + ("claim " * 80)],
        "Attached files:\n\n" + ("x" * 500),
        "What is the policy?",
        budget_chars=180,
    )
    assert "Stay helpful." in prompt
    assert "context.trimmed:files" in traces or "context.trimmed:knowledge" in traces
    assert len(prompt) + len("What is the policy?") <= 180


def test_prompt_budget_rejects_a_system_prompt_that_cannot_fit():
    manifest = _manifest(system_prompt="S" * 300)
    with pytest.raises(ServiceError) as exc:
        PromptCompositionService.compose_within_budget(manifest, None, [], None, "hi", budget_chars=50)
    assert exc.value.code == "CONTEXT_TOO_LARGE"


@pytest.mark.asyncio
async def test_published_execute_key_must_match_the_agent_and_the_agent_must_be_published():
    agent_id = uuid4()

    class _Repo:
        async def get_by_api_key_hash(self, digest):
            assert digest == hash_api_key("ak_live")
            return {"agent_id": agent_id, "slug": "claims-bot", "enabled": True}

    class _Manifests:
        def __init__(self, published: bool) -> None:
            self.published = published

        async def resolve(self, resolved_id, bearer_token, *, revision_id=None, published_only=False):
            if published_only and not self.published:
                raise ServiceError("AGENT_NOT_PUBLISHED", "This caller can only run a published agent revision.", 400)
            return _manifest(status="Published" if self.published else "Draft")

    published = DeploymentService(_Repo(), _Manifests(True), _Settings())
    row = await published.authenticate_for_agent(agent_id, "ak_live")
    assert row["slug"] == "claims-bot"
    await published.require_published(agent_id)

    with pytest.raises(ServiceError) as wrong_agent:
        await published.authenticate_for_agent(uuid4(), "ak_live")
    assert wrong_agent.value.code == "UNAUTHORIZED"

    draft = DeploymentService(_Repo(), _Manifests(False), _Settings())
    with pytest.raises(ServiceError) as unpublished:
        await draft.require_published(agent_id)
    assert unpublished.value.code == "AGENT_NOT_PUBLISHED"
