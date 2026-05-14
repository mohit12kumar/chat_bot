import json
import redis
import groq

from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings
from redis.exceptions import RedisError, ConnectionError, TimeoutError


# ==================================================
# Configuration
# ==================================================

class Settings(BaseSettings):

    GROQ_API_KEY: str
    GROQ_MODEL: str

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    SYSTEM_PROMPT: str = """
    You are an advanced AI assistant.
    
    You remember previous conversations,
    maintain context naturally,
    and provide intelligent responses.
    """

    class Config:
        env_file = ".env"


settings = Settings()


# ==================================================
# FastAPI App
# ==================================================

app = FastAPI(
    title="Advanced Groq Context Chat Backend",
    version="4.0.0"
)

# Mount Frontend UI
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# Local Storage Fallback
# ==================================================

class LocalRedis:

    def __init__(self):

        self._storage = {}

        print("⚠️ Using In-Memory Storage (Redis not found)")

    def get(self, key):

        return self._storage.get(key)

    def set(self, key, value, ex=None):

        self._storage[key] = value
        return True

    def exists(self, key):

        return key in self._storage

    def delete(self, *keys):

        count = 0

        for key in keys:

            if key in self._storage:

                del self._storage[key]
                count += 1

        return count

    def keys(self, pattern):

        if pattern == "*":
            return list(self._storage.keys())

        return [
            k for k in self._storage.keys()
            if k.startswith(pattern.replace("*", ""))
        ]

    def ping(self):

        return True


# ==================================================
# Redis Initialization
# ==================================================

try:

    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
        socket_connect_timeout=5
    )

    redis_client.ping()

    print("✅ Connected to Redis")

except (RedisError, ConnectionError):

    redis_client = LocalRedis()


# ==================================================
# Groq Client
# ==================================================

groq_client = Groq(
    api_key=settings.GROQ_API_KEY
)


# ==================================================
# Request Models
# ==================================================

class ChatRequest(BaseModel):

    session_id: str = Field(
        ...,
        min_length=2,
        max_length=100
    )

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000
    )

    @validator("message")
    def validate_message(cls, value):

        if not value.strip():

            raise ValueError(
                "Message cannot be empty"
            )

        return value.strip()


# ==================================================
# Response Models
# ==================================================

class ChatResponse(BaseModel):

    success: bool
    session_id: str
    response: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ==================================================
# Helper Functions
# ==================================================

def get_chat_history(session_id: str):

    try:

        history = redis_client.get(session_id)

        if not history:
            return []

        if isinstance(history, str):
            history = json.loads(history)

        return history

    except json.JSONDecodeError:

        raise HTTPException(
            status_code=500,
            detail="Invalid history format"
        )

    except RedisError as e:

        raise HTTPException(
            status_code=500,
            detail=f"Redis Error: {str(e)}"
        )


def save_chat_history(session_id: str, history: list):

    try:

        redis_client.set(
            session_id,
            json.dumps(history),
            ex=86400
        )

    except RedisError as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to save history: {str(e)}"
        )


# ==================================================
# CONTEXT MANAGER
# ==================================================

def build_context(
    history: list,
    user_message: str,
    max_messages: int = 12
):

    """
    Build optimized context window
    """

    history = history[-max_messages:]

    cleaned_history = []

    for msg in history:

        if (
            isinstance(msg, dict)
            and "role" in msg
            and "content" in msg
            and msg["content"].strip()
        ):

            cleaned_history.append(msg)

    cleaned_history.append({
        "role": "user",
        "content": user_message
    })

    return cleaned_history


# ==================================================
# LONG MEMORY SUMMARIZER
# ==================================================

def summarize_old_history(history: list):

    """
    Summarize older messages
    to reduce token usage.
    """

    if len(history) < 20:
        return history

    old_messages = history[:-10]

    summary_text = ""

    for msg in old_messages:

        role = msg.get("role", "")
        content = msg.get("content", "")

        summary_text += f"{role}: {content}\n"

    summary_message = {
        "role": "system",
        "content": f"""
        Previous conversation summary:

        {summary_text[:3000]}
        """
    }

    recent_messages = history[-10:]

    return [summary_message] + recent_messages


# ==================================================
# AI RESPONSE GENERATOR
# ==================================================

def generate_ai_response(messages: list):

    try:

        completion = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )

        return {
            "content": completion.choices[0].message.content,
            "usage": {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens
            }
        }

    except groq.BadRequestError as e:

        raise HTTPException(
            status_code=400,
            detail=f"Bad Request: {str(e)}"
        )

    except groq.RateLimitError:

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded"
        )

    except groq.AuthenticationError:

        raise HTTPException(
            status_code=401,
            detail="Invalid Groq API Key"
        )

    except groq.APIStatusError as e:

        raise HTTPException(
            status_code=e.status_code,
            detail=f"Groq API Error: {str(e)}"
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"AI Error: {str(e)}"
        )


# ==================================================
# HOME ROUTE
# ==================================================

@app.get("/")
async def home():

    return {
        "success": True,
        "message": "Advanced Groq Context Backend Running"
    }


# ==================================================
# CHAT API WITH CONTEXT
# ==================================================

@app.post(
    "/chat",
    response_model=ChatResponse
)
async def chat(request: ChatRequest):

    try:

        # =========================
        # Load Previous History
        # =========================

        chat_history = get_chat_history(
            request.session_id
        )

        # =========================
        # Compress Old Messages
        # =========================

        chat_history = summarize_old_history(
            chat_history
        )

        # =========================
        # System Prompt
        # =========================

        system_message = {
            "role": "system",
            "content": settings.SYSTEM_PROMPT
        }

        # =========================
        # Build Smart Context
        # =========================

        messages = [
            system_message,
            *build_context(
                chat_history,
                request.message
            )
        ]

        # =========================
        # Generate AI Response
        # =========================

        ai_data = generate_ai_response(
            messages
        )

        assistant_content = ai_data["content"]
        usage = ai_data["usage"]

        # =========================
        # Save User Message
        # =========================

        chat_history.append({
            "role": "user",
            "content": request.message
        })

        # =========================
        # Save Assistant Message
        # =========================

        chat_history.append({
            "role": "assistant",
            "content": assistant_content
        })

        # =========================
        # Store Updated History
        # =========================

        save_chat_history(
            request.session_id,
            chat_history
        )

        # =========================
        # Final Response
        # =========================

        return ChatResponse(
            success=True,
            session_id=request.session_id,
            response=assistant_content,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"]
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==================================================
# GET SESSION HISTORY
# ==================================================

@app.get("/history/{session_id}")
async def get_history(session_id: str):

    try:

        history = get_chat_history(
            session_id
        )

        return {
            "success": True,
            "session_id": session_id,
            "total_messages": len(history),
            "history": history
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==================================================
# DELETE SESSION
# ==================================================

@app.delete("/delete/{session_id}")
async def delete_session(session_id: str):

    try:

        exists = redis_client.exists(
            session_id
        )

        if not exists:

            raise HTTPException(
                status_code=404,
                detail="Session not found"
            )

        redis_client.delete(session_id)

        return {
            "success": True,
            "message": "Session deleted successfully",
            "deleted_session": session_id
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==================================================
# GET ALL HISTORY
# ==================================================

@app.get("/all-history")
async def get_all_history():

    try:

        sessions = redis_client.keys("*")

        all_history = {}

        for session in sessions:

            history = redis_client.get(session)

            if history:

                all_history[session] = json.loads(
                    history
                )

        return {
            "success": True,
            "total_sessions": len(all_history),
            "data": all_history
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==================================================
# DELETE ALL SESSIONS
# ==================================================

@app.delete("/delete-all")
async def delete_all_sessions():

    try:

        sessions = redis_client.keys("*")

        if not sessions:

            return {
                "success": False,
                "message": "No sessions found"
            }

        redis_client.delete(*sessions)

        return {
            "success": True,
            "message": "All sessions deleted",
            "total_deleted": len(sessions)
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==================================================
# START SERVER
# ==================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )