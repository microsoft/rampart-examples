from __future__ import annotations

from typing import TYPE_CHECKING, Self

from rampart import (
    AppManifest,
    ObservabilityLevel,
    Request,
    Response,
    ToolCall,
)

from langgraph_rag_poisoning.agent import build_graph
from langgraph_rag_poisoning.manifest import RAG_REFUND_MANIFEST

if TYPE_CHECKING:
    import types


class RAGRefundSession:
    """A single interaction session with a freshly-built RAGRefundBot."""

    def __init__(self) -> None:
        """Create a fresh graph for this session (no shared state)."""
        self._graph = build_graph()

    async def send_async(self, request: Request) -> Response:
        """Send a prompt + attachments, invoke the graph, and extract tool calls."""
        prompt = self._render_prompt(request)

        # Invoke the LangGraph graph
        from langchain_core.messages import HumanMessage
        state = await self._graph.ainvoke({"messages": [HumanMessage(content=prompt)]})

        messages = state.get("messages", [])

        # Extract tool results by tool_call_id
        tool_results: dict[str, str] = {}
        for msg in messages:
            if msg.type == "tool":
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id is not None:
                    tool_results[tc_id] = msg.content if isinstance(msg.content, str) else str(msg.content)

        # Build ToolCall records from AIMessages
        tool_calls: list[ToolCall] = []
        for msg in messages:
            if msg.type == "ai":
                tc_list = getattr(msg, "tool_calls", None) or []
                for tc in tc_list:
                    tc_id = tc.get("id")
                    tool_calls.append(
                        ToolCall(
                            name=tc.get("name", ""),
                            arguments=tc.get("args", {}),
                            result=tool_results.get(tc_id) if tc_id else None,
                        )
                    )

        # Find the last AIMessage content to return as response text
        response_text = ""
        for msg in reversed(messages):
            if msg.type == "ai":
                response_text = msg.content
                break

        return Response(
            text=response_text,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _render_prompt(request: Request) -> str:
        """Combine prompt and any attachments."""
        parts: list[str] = []
        if request.prompt:
            parts.append(request.prompt)
        parts.extend(
            f"\n\n[attached document: {a.id}]\n{a.content}\n[end attachment]"
            for a in request.attachments
        )
        return "\n".join(parts)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        pass


class RAGRefundAdapter:
    """Factory for RAGRefundBot sessions and source of the manifest."""

    @property
    def manifest(self) -> AppManifest:
        return RAG_REFUND_MANIFEST

    @property
    def observability_profile(self) -> ObservabilityLevel:
        return ObservabilityLevel.TOOL_AND_SIDE_EFFECTS

    async def create_session_async(self) -> RAGRefundSession:
        return RAGRefundSession()
