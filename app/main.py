import json
import redis

from fastapi import FastAPI, HTTPException, status
from groq import Groq
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from redis.exceptions import RedisError


# ==================================================
# Configuration
# ==================================================

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


# ==================================================
# FastAPI App
# ==================================================

app = FastAPI(
    title="Advanced Groq Chat Backend",
    version="3.0.0"
)


# ==================================================
# Redis Client
# ==================================================

try:

    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True
    )

    redis_client.ping()

except RedisError as e:

    raise Exception(f"Redis Connection Error: {str(e)}")


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


class HistoryRequest(BaseModel):

    session_id: str = Field(
        ...,
        min_length=2,
        max_length=100
    )


class DeleteRequest(BaseModel):

    session_id: str = Field(
        ...,
        min_length=2,
        max_length=100
    )


# ==================================================
# Response Models
# ==================================================

class ChatResponse(BaseModel):

    success: bool
    session_id: str
    response: str


class HistoryResponse(BaseModel):

    success: bool
    session_id: str
    total_messages: int
    history: list


class DeleteResponse(BaseModel):

    success: bool
    message: str
    deleted_session: str


class ErrorResponse(BaseModel):

    success: bool
    error: str


# ==================================================
# Helper Functions
# ==================================================

def get_chat_history(session_id: str):

    try:

        history = redis_client.get(session_id)

        if history:
            return json.loads(history)

        return []

    except json.JSONDecodeError:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid history format in Redis"
        )

    except RedisError as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save history: {str(e)}"
        )


def generate_ai_response(messages: list):

    try:

        completion = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=2
        )

        return completion.choices[0].message.content

    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Groq API Error: {str(e)}"
        )


# ==================================================
# Home API
# ==================================================

@app.get("/")
async def home():

    return {
        "success": True,
        "message": "Advanced Groq Backend Running"
    }


# ==================================================
# Chat API
# ==================================================

@app.post(
    "/chat",
    response_model=ChatResponse
)
async def chat(request: ChatRequest):

    try:

        # Load previous history
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

        # Generate AI response
        assistant_response = generate_ai_response(
            messages
        )

        # Save messages
        chat_history.append(user_message)

        chat_history.append({
            "role": "assistant",
            "content": assistant_response
        })

        # Save updated history
        save_chat_history(
            request.session_id,
            chat_history
        )

        return ChatResponse(
            success=True,
            session_id=request.session_id,
            response=assistant_response
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================================================
# History API
# ==================================================

@app.post(
    "/history",
    response_model=HistoryResponse
)
async def get_history(request: HistoryRequest):

    try:

        history = get_chat_history(
            request.session_id
        )

        if not history:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No history found for this session"
            )

        return HistoryResponse(
            success=True,
            session_id=request.session_id,
            total_messages=len(history),
            history=history
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================================================
# Delete Session API
# ==================================================

@app.delete(
    "/delete/{session_id}",
    response_model=DeleteResponse
)
async def delete_session(session_id: str):

    try:

        exists = redis_client.exists(
            session_id
        )

        if not exists:

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )

        redis_client.delete(
            session_id
        )

        return DeleteResponse(
            success=True,
            message="Session deleted successfully",
            deleted_session=session_id
        )

    except HTTPException:
        raise

    except RedisError as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Redis Error: {str(e)}"
        )

    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================================================
# Get ALL Sessions API
# ==================================================

@app.get("/all-history")
async def get_all_history():

    try:

        sessions = redis_client.keys("*")

        all_history = {}

        for session in sessions:

            history = redis_client.get(session)

            if history:
                all_history[session] = json.loads(history)

        return {
            "success": True,
            "total_sessions": len(all_history),
            "data": all_history
        }

    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================================================
# Delete ALL Sessions API
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
            "message": "All sessions deleted successfully",
            "total_deleted": len(sessions)
        }

    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
