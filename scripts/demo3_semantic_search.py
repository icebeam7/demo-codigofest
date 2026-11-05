
import json
import os

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
from azure.cosmos.agent_memory import CosmosMemoryClient

load_dotenv()

USER_ID = "travel-user-001"

QUERY = (
    "Quiero pasar tres días en Praga. "
    "¿Qué preferencias de transporte, alojamiento "
    "y actividades debo considerar?"
)

DATABASE = os.getenv("COSMOS_DB_DATABASE", "ai_memory")
CONTAINER = os.getenv("COSMOS_DB_MEMORIES_CONTAINER", "memories")


def create_memory_client():
    client = CosmosMemoryClient(
        cosmos_endpoint=os.environ["COSMOS_DB_ENDPOINT"],
        cosmos_database=DATABASE,
        cosmos_container=CONTAINER,
        ai_foundry_endpoint=os.environ["AI_FOUNDRY_ENDPOINT"],
        embedding_deployment_name=os.getenv(
            "AI_FOUNDRY_EMBEDDING_DEPLOYMENT_NAME",
            "text-embedding-3-large"
        ),
        chat_deployment_name=os.getenv(
            "AI_FOUNDRY_CHAT_DEPLOYMENT_NAME",
            "gpt-4o-mini"
        ),
        use_default_credential=True
    )

    client.connect_cosmos()
    return client


def search_memories(memory, query):
    print("\n=== ORIGINAL SEMANTIC SEARCH ===")
    print("Query:", query)

    results = memory.search_cosmos(
        user_id=USER_ID,
        search_terms=query,
        top_k=15
    )

    for index, item in enumerate(results, start=1):
        print(f"\n#{index} [{item.get('type', 'unknown')}]")
        print(item.get("content", ""))

    return results


def rerank_memories(results, query):
    print("\n=== SEMANTIC RERANKER ===")

    if not results:
        print("No memories found.")
        return []

    # Direct Cosmos DB SDK for Semantic Reranker
    cosmos = CosmosClient(
        os.environ["COSMOS_DB_ENDPOINT"],
        credential=DefaultAzureCredential()
    )

    container = (
        cosmos
        .get_database_client(DATABASE)
        .get_container_client(CONTAINER)
    )

    documents = [
        json.dumps({
            "id": str(item.get("id", index)),
            "content": item.get("content", ""),
            "type": item.get("type", "")
        }, ensure_ascii=False)
        for index, item in enumerate(results)
    ]

    # Reranker is applied to the retrieved candidates.
    response = container.semantic_rerank(
        context=query,
        documents=documents,
        options={
            "return_documents": True,
            "top_k": min(5, len(documents)),
            "sort": True,
            "document_type": "json",
            "target_paths": "content"
        }
    )

    ordered_memories = []

    for rank, result in enumerate(response["Scores"], start=1):
        original_index = result["index"]
        score = result["score"]
        memory = results[original_index]

        ordered_memories.append(memory)

        print(f"\nRank #{rank}")
        print(f"Original rank: #{original_index + 1}")
        print(f"Reranker score: {score:.4f}")
        print("Content:", memory.get("content", ""))

    print("\nLatency:", response.get("latency", {}))
    print("Token usage:", response.get("token_usage", {}))

    return ordered_memories


def build_agent_context(memories):
    return "\n".join(
        f"- {item.get('content', '')}"
        for item in memories
        if item.get("content")
    )


def main():
    memory = create_memory_client()

    # Step 1: Retrieve candidate memories
    results = search_memories(memory, QUERY)

    # Step 2: Rerank by relevance
    ranked = rerank_memories(results, QUERY)

    # Step 3: Prepare context for our AI agent
    context = build_agent_context(ranked)

    print("\n=== CONTEXT FOR AI AGENT ===")
    print(context)


if __name__ == "__main__":
    main()
