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
    title="Groq Chat Backend",
    version="2.0.0"
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
# Models
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

    history = redis_client.get(session_id)

    if history:
        return json.loads(history)

    return []


def save_chat_history(session_id: str, history: list):

    redis_client.set(
        session_id,
        json.dumps(history),
        ex=86400
    )


def generate_ai_response(messages: list):

    completion = groq_client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=messages,
        temperature=0.7
    )

    return completion.choices[0].message.content


# =========================
# Home API
# =========================

@app.get("/")
async def home():

    return {
        "message": "Groq Chat Backend Running"
    }


# =========================
# Chat API
# =========================

@app.post("/chat")
async def chat(request: ChatRequest):

    try:

        # Load old history
        chat_history = get_chat_history(
            request.session_id
        )

        # User message
        user_message = {
            "role": "user",
            "content": request.message
        }

        # System prompt
        system_message = {
            "role": "system",
            "content": settings.SYSTEM_PROMPT
        }

        # Final messages
        messages = [
            system_message,
            *chat_history,
            user_message
        ]

        # Generate response
        assistant_response = generate_ai_response(
            messages
        )

        # Save messages
        chat_history.append(user_message)

        chat_history.append({
            "role": "assistant",
            "content": assistant_response
        })

        # Store in Redis
        save_chat_history(
            request.session_id,
            chat_history
        )

        return {
            "session_id": request.session_id,
            "response": assistant_response
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================
# Get Single Session History
# =========================

@app.get("/history/{session_id}")
async def get_history(session_id: str):

    try:

        history = get_chat_history(session_id)

        return {
            "session_id": session_id,
            "history": history
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================
# Get ALL Sessions History
# =========================

@app.get("/all-history")
async def get_all_history():

    try:

        all_sessions = redis_client.keys("*")

        all_data = {}

        for session_id in all_sessions:

            history = redis_client.get(session_id)

            if history:
                all_data[session_id] = json.loads(history)

        return {
            "total_sessions": len(all_data),
            "data": all_data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================
# Delete Single Session
# =========================

@app.delete("/delete/{session_id}")
async def delete_session(session_id: str):

    try:

        exists = redis_client.exists(session_id)

        if not exists:

            raise HTTPException(
                status_code=404,
                detail="Session not found"
            )

        redis_client.delete(session_id)

        return {
            "message": f"Session '{session_id}' deleted successfully"
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# =========================
# Delete ALL Sessions
# =========================

@app.delete("/delete-all")
async def delete_all_sessions():

    try:

        all_sessions = redis_client.keys("*")

        if not all_sessions:

            return {
                "message": "No sessions found"
            }

        redis_client.delete(*all_sessions)

        return {
            "message": "All sessions deleted successfully",
            "total_deleted": len(all_sessions)
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
