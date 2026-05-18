import streamlit as st
import requests
import json
import uuid

# Configuration
API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI Context Chat", page_icon="🤖", layout="wide")

def inject_custom_css():
    st.markdown("""
        <style>
        /* Main background gradient */
        .stApp {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        }
        
        /* Text styling */
        p, span, div, label {
            color: #000000 !important;
        }
        
        /* Sidebar styling */
        [data-testid="stSidebar"] {
            background-color: rgba(255, 255, 255, 0.8) !important;
            backdrop-filter: blur(10px);
            border-right: 2px solid #e1e4e8;
        }
        
        /* Stylish rounded buttons with hover effects */
        .stButton>button {
            background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
            color: white !important;
            border-radius: 20px;
            border: none;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0,0,0,0.15);
            background: linear-gradient(90deg, #00f2fe 0%, #4facfe 100%);
        }
        
        /* Colorful headers */
        h1, h2, h3 {
            color: #000000 !important;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        /* Chat Input */
        .stChatInputContainer {
            border-radius: 20px !important;
            border: 2px solid #4facfe !important;
        }
        </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# --- Session State Initialization ---
if "session_id" not in st.session_state:
    st.session_state.session_id = f"session_{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Sidebar ---
with st.sidebar:
    st.title("🤖 RAG Chatbot")
    
    # 1. Document Upload
    st.header("Document Upload")
    st.write("Upload a PDF or TXT to add context to the AI's knowledge base.")
    uploaded_file = st.file_uploader("Upload Book/Doc", type=["pdf", "txt"])
    
    if st.button("Upload to Database") and uploaded_file:
        with st.spinner("Uploading..."):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
            try:
                res = requests.post(f"{API_URL}/upload-document", files=files)
                if res.status_code == 200:
                    st.success(res.json().get("message", "Upload complete!"))
                else:
                    st.error(f"Error: {res.text}")
            except Exception as e:
                st.error(f"Connection error: Make sure your FastAPI server is running. Error: {e}")
                
    st.divider()
    
    # 2. Session Management
    st.header("Session Management")
    st.write(f"**Current:** `{st.session_state.session_id}`")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("➕ New"):
            st.session_state.session_id = f"session_{uuid.uuid4().hex[:8]}"
            st.session_state.messages = []
            st.rerun()
    with col2:
        if st.button("📦 Archive"):
            try:
                requests.post(f"{API_URL}/archive/{st.session_state.session_id}")
                st.success("Archived!")
                st.session_state.session_id = f"session_{uuid.uuid4().hex[:8]}"
                st.session_state.messages = []
                st.rerun()
            except Exception as e:
                st.error("Error")
    with col3:
        if st.button("🗑️ Delete"):
            try:
                requests.delete(f"{API_URL}/delete/{st.session_state.session_id}")
                st.success("Deleted!")
                st.session_state.session_id = f"session_{uuid.uuid4().hex[:8]}"
                st.session_state.messages = []
                st.rerun()
            except Exception as e:
                st.error("Error")

    st.divider()
    
    # 3. History & Search
    st.header("Previous Sessions")
    search_query = st.text_input("🔍 Search history...", "")
    
    try:
        all_hist_res = requests.get(f"{API_URL}/all-history")
        if all_hist_res.status_code == 200:
            all_sessions = all_hist_res.json().get("data", {})
            
            if not all_sessions:
                st.write("No active sessions.")
            else:
                for s_id, msgs in reversed(list(all_sessions.items())):
                    preview = "New Chat"
                    is_archived = False
                    if msgs:
                        preview = msgs[-1].get("content", "")[:30] + "..."
                        is_archived = msgs[-1].get("is_archived", False)
                    
                    display_title = f"📦 [Archived] {preview}" if is_archived else f"💬 {preview}"
                    
                    if search_query.lower() in s_id.lower() or search_query.lower() in preview.lower():
                        with st.expander(display_title):
                            st.caption(f"ID: {s_id}")
                            if st.button("Load Session", key=f"load_{s_id}"):
                                st.session_state.session_id = s_id
                                st.session_state.messages = []
                                st.rerun()
        else:
            st.write("Failed to load history.")
    except Exception as e:
        st.write("Could not connect to database.")

# --- Main Chat Interface ---
st.title("Chat with your Documents")

# Load existing history from backend if our local state is empty
if not st.session_state.messages:
    try:
        hist_res = requests.get(f"{API_URL}/history/{st.session_state.session_id}")
        if hist_res.status_code == 200:
            history = hist_res.json().get("history", [])
            for msg in history:
                role = "assistant" if msg["role"] in ["assistant", "system"] else "user"
                st.session_state.messages.append({
                    "role": role,
                    "content": msg["content"]
                })
    except:
        pass

# Display chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat Input
if prompt := st.chat_input("Ask a question about your documents..."):
    # Append and show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Append and stream assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            # Send streaming request to FastAPI backend
            response = requests.post(
                f"{API_URL}/chat",
                json={"session_id": st.session_state.session_id, "message": prompt},
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        try:
                            data = json.loads(decoded_line)
                            
                            if "text" in data and not data.get("done", False):
                                full_response += data["text"]
                                message_placeholder.markdown(full_response + "▌")
                                
                            elif data.get("done", False):
                                full_response = data.get("full_content", full_response)
                                message_placeholder.markdown(full_response)
                                
                        except json.JSONDecodeError:
                            continue
                
                st.session_state.messages.append({"role": "assistant", "content": full_response})
            else:
                st.error(f"Error from server: {response.text}")
                
        except Exception as e:
            st.error(f"Failed to connect to the backend. Is FastAPI running? Error: {e}")
