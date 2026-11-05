
import os
import uuid
import time

from dotenv import load_dotenv
from azure.identity import (
    DefaultAzureCredential,
    get_bearer_token_provider
)
from azure.cosmos.agent_memory import (
    CosmosMemoryClient,
    DurableFunctionProcessor
)
from openai import AzureOpenAI

load_dotenv()

# -------------------------------------------------
# Configuration
# -------------------------------------------------

USER_ID = "travel-user-001"

PLANNING_THREAD = f"planning-{uuid.uuid4()}"
BUDGET_THREAD = f"budget-{uuid.uuid4()}"

CHAT_MODEL = os.getenv(
    "AI_FOUNDRY_CHAT_DEPLOYMENT_NAME",
    "gpt-4o-mini"
)

os.environ["MEMORY_PROCESSOR_OWNER"] = "durable"

# -------------------------------------------------
# Cosmos DB Agent Memory Toolkit
# -------------------------------------------------

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
    chat_deployment_name=CHAT_MODEL,
    use_default_credential=True,
    processor=DurableFunctionProcessor()
)

memory.connect_cosmos()

# -------------------------------------------------
# Microsoft Foundry / Azure OpenAI
# -------------------------------------------------

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

# -------------------------------------------------
# Agent helper
# -------------------------------------------------

def generate_response(system_prompt, message, context=""):
    result = llm.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    system_prompt
                    + "\n\nPersistent user memory:\n"
                    + context
                )
            },
            {
                "role": "user",
                "content": message
            }
        ]
    )
    return result.choices[0].message.content or ""


def save_turn(thread_id, role, content):
    memory.upsert_memory(
        user_id=USER_ID,
        thread_id=thread_id,
        role=role,
        content=content
    )


# -------------------------------------------------
# Agent 1: Travel Planner
# -------------------------------------------------

def planning_agent():
    print("\n=== AGENT 1: TRAVEL PLANNER ===")

    user_message = (
        "Quiero visitar Praga durante tres días. "
        "Me interesan los museos y los lugares históricos. "
        "Prefiero viajar en tren. "
        "Mi presupuesto de hotel es de 120 euros por noche."
    )

    print("\nUser:", user_message)

    save_turn(
        PLANNING_THREAD,
        "user",
        user_message
    )

    response = generate_response(
        system_prompt=(
            "You are a travel planning assistant. "
            "Create short itineraries based on user preferences. "
            "Do not invent bookings or availability. "
            "Always respond in Spanish."
        ),
        message=user_message
    )

    print("\nTravel planner:", response)

    save_turn(
        PLANNING_THREAD,
        "agent",
        response
    )

    print("\n[EVENT]")
    print("Two conversation turns persisted in Cosmos DB.")
    print("Change Feed can now trigger Durable Functions.")

    return response


# -------------------------------------------------
# Agent 2: Budget Advisor
# -------------------------------------------------

def budget_agent():
    print("\n=== AGENT 2: BUDGET ADVISOR ===")

    user_message = (
        "Ayúdame a preparar un presupuesto para "
        "mis próximas vacaciones, teniendo en cuenta "
        "mis preferencias anteriores."
    )

    # Read memories across all threads for this user
    memories = memory.search_cosmos(
        user_id=USER_ID,
        search_terms=(
            "travel preferences, hotel budget, "
            "transport and cultural activities"
        ),
        top_k=8
    )

    context = "\n".join(
        f"- {item.get('content', '')}"
        for item in memories
        if item.get("content")
    )

    user_summary = memory.get_user_summary(
        user_id=USER_ID
    )

    if user_summary:
        context += f"\n\nUser profile:\n{user_summary}"

    print("\n[SHARED MEMORY]")
    print(context or "No derived memories found yet.")

    save_turn(
        BUDGET_THREAD,
        "user",
        user_message
    )

    response = generate_response(
        system_prompt=(
            "You are a travel budget advisor. "
            "Use user memories to personalize "
            "a travel budget. "
            "Do not invent actual prices, offers "
            "or hotel availability. "
            "Clearly label estimates as illustrative. "
            "Always respond in Spanish."
        ),
        message=user_message,
        context=context
    )

    print("\nBudget advisor:", response)

    save_turn(
        BUDGET_THREAD,
        "agent",
        response
    )

    return response


# -------------------------------------------------
# Orchestration of the live demonstration
# -------------------------------------------------

def main():
    print("===================================")
    print("COSMOS DB MULTI-AGENT MEMORY DEMO")
    print("===================================")

    print("User ID:", USER_ID)
    print("Planning thread:", PLANNING_THREAD)
    print("Budget thread:", BUDGET_THREAD)

    planning_agent()

    print("\n[AZURE DURABLE FUNCTIONS]")
    print("Processing runs asynchronously.")
    print("Check the Function App and Cosmos DB.")

    input(
        "\nOnce derived memories are visible, "
        "press Enter to continue..."
    )

    budget_agent()

    print("\n=== DEMO COMPLETED ===")
    print("Both agents used the same Cosmos DB memory store.")


if __name__ == "__main__":
    main()
