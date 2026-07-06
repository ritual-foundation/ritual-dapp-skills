# RagAgent — On-Chain RAG Agent for Ritual Chain

Fetches a document via HTTP precompile (0x0801) and answers questions about it using the LLM precompile (0x0802). Document content and answers are stored on-chain.

Flow: submitQuery(docUrl, question) -> fetchDoc(queryId, executor, ttl) -> askQuestion(queryId, executor, ttl) -> getAnswer(queryId)

Deployed: 0x7366D14edEeC3Bce5bDC3e33C57e620461115465 (Ritual testnet, Chain ID 1979)
