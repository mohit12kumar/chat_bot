import json

import redis
from fastapi import FastAPI, HTTPException
from groq import Groq
from pydantic import BaseModel
from pydantic_settings import BaseSettings


# =========================
# Configuration
# =========================

class Settings(BaseSettings):
    GROQ_API_KEY: str
    GROQ_MODEL: str

    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int

    SYSTEM_PROMPT: str

    class Config:
        env_file = ".env"


settings = Settings()


# =========================
# FastAPI App
# =========================

app = FastAPI(
    title="Groq LLM Backend",
    version="1.0.0"
)


# =========================
# Redis Client
# =========================

redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True
)


# =========================
# Groq Client
# =========================

groq_client = Groq(
    api_key=settings.GROQ_API_KEY
)


# =========================
# Request / Response Models
# =========================

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response: str


# =========================
# Helper Functions
# =========================

def get_chat_history(session_id: str):
    """
    Load previous chat history from Redis.
    """

    history = redis_client.get(session_id)

    if not history:
        return []

    return json.loads(history)


def save_chat_history(session_id: str, history: list):
    """
    Save updated chat history to Redis.
    """

    redis_client.set(
        session_id,
        json.dumps(history)
    )


def generate_ai_response(messages: list):
    """
    Send messages to Groq API and return response.
    """

    completion = groq_client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=messages,
        temperature=0.7,
    )

    return completion.choices[0].message.content


# =========================
# Chat Endpoint
# =========================

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):

    try:
        # 1. Load previous conversation
        chat_history = get_chat_history(request.session_id)

        # 2. Latest user message
        user_message = {
            "role": "user",
            "content": request.message
        }

        # 3. System prompt
        system_message = {
            "role": "system",
            "content": settings.SYSTEM_PROMPT
        }

        # 4. Build final message payload
        messages = [
            system_message,
            *chat_history,
            user_message
        ]

        # 5. Generate assistant response
        assistant_response = generate_ai_response(messages)

        # 6. Save latest user message
        chat_history.append(user_message)

        # 7. Save assistant response
        chat_history.append({
            "role": "assistant",
            "content": assistant_response
        })

        # 8. Store updated history
        save_chat_history(
            request.session_id,
            chat_history
        )

        # 9. Return response
        return ChatResponse(
            session_id=request.session_id,
            response=assistant_response
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )