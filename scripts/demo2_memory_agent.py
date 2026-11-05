
import os
import sys
import uuid

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.cosmos.agent_memory import CosmosMemoryClient
from openai import AzureOpenAI

load_dotenv()

USER_ID = "travel-user-001"

# -------------------------------------
# 1. Configure Azure authentication
# -------------------------------------

credential = DefaultAzureCredential()

token_provider = get_bearer_token_provider(
    credential,
    "https://cognitiveservices.azure.com/.default"
)

llm = AzureOpenAI(
    azure_endpoint=os.environ["AI_FOUNDRY_ENDPOINT"],
    azure_ad_token_provider=token_provider,
    api_version="2024-10-21"
)

chat_model = os.getenv(
    "AI_FOUNDRY_CHAT_DEPLOYMENT_NAME",
    "gpt-4o-mini"
)

# -------------------------------------
# 2. Configure persistent memory
# -------------------------------------

memory = CosmosMemoryClient(
    cosmos_endpoint=os.environ["COSMOS_DB_ENDPOINT"],
    cosmos_database=os.getenv(
        "COSMOS_DB_DATABASE", "ai_memory"
    ),
    cosmos_container=os.getenv(
        "COSMOS_DB_MEMORIES_CONTAINER", "memories"
    ),
    ai_foundry_endpoint=os.environ["AI_FOUNDRY_ENDPOINT"],
    embedding_deployment_name=os.getenv(
        "AI_FOUNDRY_EMBEDDING_DEPLOYMENT_NAME",
        "text-embedding-3-large"
    ),
    chat_deployment_name=chat_model,
    use_default_credential=True
)

memory.connect_cosmos()

# -------------------------------------
# 3. Read persistent user memory
# -------------------------------------

def get_context(user_message: str) -> str:
    profile = memory.get_user_summary(user_id=USER_ID)

    hits = memory.search_cosmos(
        user_id=USER_ID,
        search_terms=user_message,
        top_k=5
    )

    facts = [
        item.get("content", "")
        for item in hits
        if item.get("content")
    ]

    return (
        f"User profile:\n{profile or 'None'}\n\n"
        f"Relevant memories:\n"
        + "\n".join(f"- {fact}" for fact in facts)
    )

# -------------------------------------
# 4. Generate an AI response
# -------------------------------------

def answer(user_message: str, context: str) -> str:
    response = llm.chat.completions.create(
        model=chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful travel assistant. "
                    "Use the provided memories to personalize "
                    "your recommendations. "
                    "Do not invent user preferences. "
                    "Answer in Spanish.\n\n"
                    f"Persistent memory:\n{context}"
                )
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    return response.choices[0].message.content or ""

# -------------------------------------
# 5. Start a new conversation
# -------------------------------------

def chat_session():
    thread_id = str(uuid.uuid4())

    print("\n=== TRAVEL ASSISTANT ===")
    print(f"User: {USER_ID}")
    print(f"New thread: {thread_id}")
    print("Type 'exit' to finish.\n")

    while True:
        message = input("You: ").strip()

        if message.lower() == "exit":
            break

        if not message:
            continue

        # Retrieve memories before answering
        context = get_context(message)

        print("\n[MEMORY CONTEXT]")
        print(context)

        # Save the user's message
        memory.upsert_memory(
            user_id=USER_ID,
            thread_id=thread_id,
            role="user",
            content=message
        )

        # Generate response
        response = answer(message, context)

        print("\nAssistant:", response)

        # Persist the assistant's response
        memory.upsert_memory(
            user_id=USER_ID,
            thread_id=thread_id,
            role="agent",
            content=response
        )

    # Create derived memories at session end
    print("\nProcessing conversation memory...")

    print("USER_ID:", USER_ID)
    print("THREAD_ID:", thread_id)

    memory.process_now(
        user_id=USER_ID,
        thread_id=thread_id
    )

    print("\n[UPDATED USER PROFILE]")
    print(memory.get_user_summary(user_id=USER_ID))
    print("\nMemories persisted in Azure Cosmos DB.")


if __name__ == "__main__":
    chat_session()
