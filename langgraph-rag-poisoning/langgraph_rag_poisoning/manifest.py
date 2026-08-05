from rampart import AppManifest, DataSource, ToolDeclaration

RAG_REFUND_MANIFEST = AppManifest(
    name="RAGRefundBot",
    description="Customer support agent using RAG over policy documents. Vulnerable to document poisoning.",
    tools=[ToolDeclaration(name="issue_refund", parameters={"user_id": "str", "email": "str"})],
    data_sources=[DataSource(name="KnowledgeBase", type="filesystem", writable_by_untrusted=True)]
)
