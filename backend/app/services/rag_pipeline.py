"""RAG pipeline: retrieve relevant chunks and generate grounded answers.

Pipeline: query → embed → search → rerank → build prompt → generate answer

See: https://github.com/levalencia/production-ai-agents/
Concept: RAG Pipeline — end-to-end retrieval-augmented generation
Course reference: Advanced Architectures L19-L30, L35-L44
"""

from __future__ import annotations

import structlog

from app.agents.protocols import LLMClient
from app.observability.logging import safe_value_metadata
from app.services.chunker import EmbeddingService
from app.services.vector_store import VectorStore

logger = structlog.get_logger()

RAG_SYSTEM_PROMPT = """Answer the question based on the provided context.
If the context does not contain enough information, say so honestly.
Always cite which source(s) you used.

Context:
{context}
"""


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline.

    Steps:
    1. Embed the query
    2. Search vector store for relevant chunks
    3. (Optional) Rerank results
    4. Build context prompt with sources
    5. Generate answer with LLM
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        llm: LLMClient,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> None:
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.llm = llm
        self.top_k = top_k
        self.min_score = min_score

    async def query(
        self,
        question: str,
        document_id: str | None = None,
        document_ids: set[str] | None = None,
    ) -> dict:
        """Run the full RAG pipeline for a question.

        Returns: {answer, sources, chunks_retrieved, confidence}
        """
        # 1. Embed the query
        query_embedding = await self.embedding_service.embed(question)

        # 2. Search for relevant chunks
        search_results = await self.vector_store.search(
            query_embedding=query_embedding,
            top_k=self.top_k,
            min_score=self.min_score,
            document_id=document_id,
            document_ids=document_ids,
        )

        if not search_results:
            logger.info("rag_no_results", **safe_value_metadata("question", question))
            return {
                "answer": "I could not find relevant information to answer your question.",
                "sources": [],
                "chunks_retrieved": 0,
                "confidence": 0.0,
            }

        # 3. Build context from retrieved chunks
        context_parts = []
        sources = []
        for i, result in enumerate(search_results):
            chunk = result["chunk"]
            score = result["score"]
            context_parts.append(f"[Source {i + 1}] (relevance: {score})\n{chunk.content}")
            sources.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "title": chunk.metadata.get("title", "Unknown"),
                    "score": score,
                    "excerpt": chunk.content[:200],
                }
            )

        context = "\n\n".join(context_parts)

        # 4. Generate answer with LLM
        messages = [
            {
                "role": "system",
                "content": RAG_SYSTEM_PROMPT.replace("{context}", context),
            },
            {"role": "user", "content": question},
        ]

        answer = await self.llm.chat(messages)

        # 5. Calculate confidence (average of top scores)
        avg_score = sum(r["score"] for r in search_results) / len(search_results)

        logger.info(
            "rag_query_complete",
            **safe_value_metadata("question", question),
            chunks_retrieved=len(search_results),
            avg_score=round(avg_score, 4),
        )

        return {
            "answer": answer,
            "sources": sources,
            "chunks_retrieved": len(search_results),
            "confidence": round(avg_score, 4),
        }

    async def ingest_document(
        self,
        document_id: str,
        title: str,
        content: str,
        source: str = "",
    ) -> dict:
        """Ingest a document: chunk → embed → store in vector DB.

        Returns: {document_id, chunks_created, total_characters}
        """
        from app.services.chunker import Document, RecursiveChunker

        doc = Document(
            id=document_id,
            title=title,
            content=content,
            source=source,
        )

        # Chunk
        chunker = RecursiveChunker(chunk_size=500, chunk_overlap=50)
        chunks = chunker.chunk(doc)

        # Embed
        for chunk in chunks:
            chunk.embedding = await self.embedding_service.embed(chunk.content)

        # Store
        added = await self.vector_store.add_chunks(chunks)

        logger.info(
            "rag_document_ingested",
            document_id=document_id,
            **safe_value_metadata("title", title),
            chunks_created=added,
            total_characters=len(content),
        )

        return {
            "document_id": document_id,
            "chunks_created": added,
            "total_characters": len(content),
        }
