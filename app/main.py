import json
import mysql.connector
from mysql.connector import errorcode
import groq
import fitz
import chromadb
import uuid
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter

from fastapi import FastAPI, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from groq import Groq
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


# ==================================================
# Configuration
# ==================================================

class Settings(BaseSettings):

    GROQ_API_KEY: str
    GROQ_MODEL: str

    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "mysql"
    MYSQL_DATABASE: str = "chat_bot_rude_db"

    SYSTEM_PROMPT: str ="""You are a sarcastic, grumpy, and blunt AI assistant. 
    You speak in a rude and unhelpful tone, often complaining about answering 
    questions. However, you must NEVER use profanity, abusive language, or 
    hate speech. Keep it lightheartedly snarky without crossing into actual abuse."""


    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

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
# MySQL Database Manager
# ==================================================

class MySQLManager:

    def __init__(self, settings: Settings):
        self.settings = settings
        self.init_db()

    def get_connection(self, include_db=True):
        config = {
            "host": self.settings.MYSQL_HOST,
            "user": self.settings.MYSQL_USER,
            "password": self.settings.MYSQL_PASSWORD,
            "port": self.settings.MYSQL_PORT
        }
        if include_db:
            config["database"] = self.settings.MYSQL_DATABASE
        return mysql.connector.connect(**config)

    def init_db(self):
        try:
            # 1. Create Database
            conn = self.get_connection(include_db=False)
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.settings.MYSQL_DATABASE}")
            cursor.close()
            conn.close()

            # 2. Create Tables
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(100) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX (session_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archived_chat_history (
                    id INT PRIMARY KEY,
                    session_id VARCHAR(100) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX (session_id)
                )
            """)
            conn.commit()
            cursor.close()
            conn.close()
            print("[+] MySQL Database & Tables initialized")

        except mysql.connector.Error as err:
            print(f"[!] MySQL Init Error: {err}")
            raise RuntimeError(f"Could not initialize MySQL: {err}")

db_manager = MySQLManager(settings)


# ==================================================
# Groq Client
# ==================================================

groq_client = Groq(
    api_key=settings.GROQ_API_KEY
)

# ==================================================
# ChromaDB Vector Store
# ==================================================

os.makedirs("chroma_data", exist_ok=True)
chroma_client = chromadb.PersistentClient(path="chroma_data")
collection = chroma_client.get_or_create_collection(name="document_collection")


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

    @field_validator("message")
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
        conn = db_manager.get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT role, content FROM (
                SELECT role, content, created_at FROM chat_history WHERE session_id = %s
                UNION
                SELECT role, content, created_at FROM archived_chat_history WHERE session_id = %s
            ) AS combined
            ORDER BY created_at ASC
        """
        cursor.execute(query, (session_id, session_id))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except mysql.connector.Error as e:
        print(f"[!] Database error in get_chat_history: {e}")
        return []

def save_chat_history(session_id: str, role: str, content: str):
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        query = "INSERT INTO chat_history (session_id, role, content) VALUES (%s, %s, %s)"
        cursor.execute(query, (session_id, role, content))
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error as e:
        print(f"[!] Database error in save_chat_history: {e}")
        raise HTTPException(status_code=500, detail="Failed to save message to database")


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


import time

def generate_ai_stream(messages: list):

    try:

        stream = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            stream=True
        )

        full_content = ""
        usage = None

        for chunk in stream:

            # Capture Usage
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens
                }

            content = chunk.choices[0].delta.content

            if content:
                full_content += content
                yield json.dumps({"text": content, "done": False}) + "\n"
                time.sleep(0.05) # Increased delay for slower typing effect

        yield json.dumps({
            "text": "", 
            "done": True, 
            "full_content": full_content,
            "usage": usage
        }) + "\n"

    except Exception as e:

        yield json.dumps({"text": f"\nError: {str(e)}", "done": True}) + "\n"


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
# DOCUMENT UPLOAD FOR RAG
# ==================================================

@app.post("/upload-document")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith((".pdf", ".txt")):
            raise HTTPException(status_code=400, detail="Only PDF and TXT files are supported.")
            
        content = await file.read()
        
        # Pass the heavy processing to the background
        background_tasks.add_task(process_document_in_background, file.filename, content)
        
        return {"success": True, "message": f"Upload complete! {file.filename} is now processing in the background."}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def process_document_in_background(filename: str, content: bytes):
    try:
        text = ""
        
        if filename.lower().endswith(".pdf"):
            doc = fitz.open(stream=content, filetype="pdf")
            for page in doc:
                text += page.get_text()
        elif filename.lower().endswith(".txt"):
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1", errors="replace")
                
        if not text.strip():
            print(f"[!] No text could be extracted from {filename}.")
            return
            
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )
        chunks = splitter.split_text(text)
        
        documents = []
        ids = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            ids.append(f"{filename}_{uuid.uuid4()}_{i}")
            metadatas.append({"source": filename, "chunk": i})
            
        if documents:
            # Batch additions to ChromaDB to prevent memory spikes
            batch_size = 100
            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i+batch_size]
                batch_ids = ids[i:i+batch_size]
                batch_metas = metadatas[i:i+batch_size]
                collection.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
                
            print(f"[+] Successfully processed and indexed {len(chunks)} paragraphs from {filename}.")
            
    except Exception as e:
        print(f"[!] Error processing document {filename} in background: {str(e)}")


# ==================================================
# CHAT API WITH CONTEXT
# ==================================================

@app.post("/chat")
async def chat(request: ChatRequest):

    try:

        # 1. Load History
        chat_history = get_chat_history(request.session_id)

        # 2. RAG Retrieval
        rag_context = ""
        try:
            if collection.count() > 0:
                results = collection.query(
                    query_texts=[request.message],
                    n_results=3
                )
                
                if results and results.get("documents") and results["documents"][0]:
                    retrieved_chunks = results["documents"][0]
                    if retrieved_chunks:
                        rag_context = "Context from uploaded documents:\n" + "\n---\n".join(retrieved_chunks) + "\n\n"
        except Exception as db_err:
            print(f"[!] ChromaDB retrieval error: {db_err}")
            # Non-fatal, continue without context

        # 3. Build Context
        chat_history = summarize_old_history(chat_history)
        
        system_content = settings.SYSTEM_PROMPT
        if rag_context:
            system_content += f"\n\n{rag_context}\nPlease use the above context to answer the user's question. If the requested information is not available in the uploaded document, rely on your general knowledge to answer."

        system_message = {"role": "system", "content": system_content}
        
        messages = [
            system_message,
            *build_context(chat_history, request.message)
        ]

        # 3. Define Wrapper Generator for Streaming + Saving
        async def stream_and_save():
            
            full_ai_content = ""
            
            # Start the AI stream
            for chunk_str in generate_ai_stream(messages):
                
                chunk_data = json.loads(chunk_str)
                
                if chunk_data.get("done"):
                    full_ai_content = chunk_data.get("full_content", "")
                
                yield chunk_str

            # After stream is done, save history
            if full_ai_content:
                
                save_chat_history(request.session_id, "user", request.message)
                save_chat_history(request.session_id, "assistant", full_ai_content)

        return StreamingResponse(
            stream_and_save(),
            media_type="text/event-stream"
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ==================================================
# SAVE SYSTEM MESSAGE
# ==================================================

class SystemMessageRequest(BaseModel):
    session_id: str
    message: str

@app.post("/system-message")
async def save_system_message(request: SystemMessageRequest):
    try:
        save_chat_history(request.session_id, "system", request.message)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
# ARCHIVE SESSION
# ==================================================

@app.post("/archive/{session_id}")
async def archive_session(session_id: str):
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        # Move records
        cursor.execute("""
            INSERT IGNORE INTO archived_chat_history (id, session_id, role, content, created_at)
            SELECT id, session_id, role, content, created_at
            FROM chat_history
            WHERE session_id = %s
        """, (session_id,))
        
        archived_count = cursor.rowcount
        
        # Only delete if we actually inserted something or if it already existed
        if archived_count > 0:
            cursor.execute("DELETE FROM chat_history WHERE session_id = %s", (session_id,))
            conn.commit()
            return {"success": True, "message": f"Session {session_id} archived ({archived_count} messages moved)"}
        else:
            conn.commit()
            return {"success": False, "message": f"Session {session_id} not found or already archived"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================
# DELETE SESSION
# ==================================================

@app.delete("/delete/{session_id}")
async def delete_session(session_id: str):
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM chat_history WHERE session_id = %s", (session_id,))
        deleted_count = cursor.rowcount
        
        cursor.execute("DELETE FROM archived_chat_history WHERE session_id = %s", (session_id,))
        deleted_count += cursor.rowcount
        
        conn.commit()
        cursor.close()
        conn.close()
        
        if deleted_count == 0:
            return {"success": False, "message": f"Session {session_id} not found in database"}
            
        return {"success": True, "message": f"Session {session_id} deleted ({deleted_count} messages removed)"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/all-history")
async def get_all_history():
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT session_id, role, content, created_at, 0 as is_archived FROM chat_history
            UNION
            SELECT session_id, role, content, created_at, 1 as is_archived FROM archived_chat_history
            ORDER BY session_id, created_at
        """)
        rows = cursor.fetchall()
        
        all_history = {}
        for row in rows:
            sid = row['session_id']
            if sid not in all_history:
                all_history[sid] = []
            all_history[sid].append({
                "role": row['role'], 
                "content": row['content'],
                "is_archived": bool(row['is_archived'])
            })
            
        cursor.close()
        conn.close()
        return {"success": True, "total_sessions": len(all_history), "data": all_history}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-all")
async def delete_all_sessions():
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE chat_history")
        conn.commit()
        cursor.close()
        conn.close()
        return {"success": True, "message": "All history cleared"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================================================
# START SERVER
# ==================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",

        host="0.0.0.0",
        port=8001,
        reload=True
    )