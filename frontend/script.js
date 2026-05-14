const API_BASE_URL = 'http://localhost:8000';
let currentSessionId = localStorage.getItem('currentSessionId') || '';

// DOM Elements
const sessionList = document.getElementById('session-list');
const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const btnCloseCurrent = document.getElementById('btn-close-current');
const currentSessionTitle = document.getElementById('current-session-title');
const currentSessionIdDisplay = document.getElementById('current-session-id');

// --- Initialization ---
async function init() {
    await loadSessions();
    if (currentSessionId) {
        await selectSession(currentSessionId);
    }
}

// --- Session Management ---

async function loadSessions() {
    try {
        const response = await fetch(`${API_BASE_URL}/all-history`);
        const data = await response.json();
        
        sessionList.innerHTML = '';
        const sessions = Object.keys(data.data || {});
        
        if (sessions.length === 0) {
            sessionList.innerHTML = '<p style="text-align: center; color: var(--text-muted); font-size: 0.8rem; margin-top: 1rem;">No active sessions</p>';
            return;
        }

        sessions.forEach(id => {
            const history = data.data[id];
            const lastMsg = history.length > 0 ? history[history.length - 1].content : 'New Chat';
            renderSessionItem(id, lastMsg);
        });
    } catch (err) {
        console.error('Failed to load sessions:', err);
    }
}

function renderSessionItem(id, lastMsg) {
    const div = document.createElement('div');
    div.className = `session-item ${id === currentSessionId ? 'active' : ''}`;
    div.onclick = () => selectSession(id);
    
    div.innerHTML = `
        <div class="session-info">
            <span class="session-name">${lastMsg.substring(0, 25)}${lastMsg.length > 25 ? '...' : ''}</span>
            <span class="session-id">ID: ${id}</span>
        </div>
        <button class="btn-close-session" onclick="event.stopPropagation(); deleteSession('${id}')">
            <i data-lucide="x"></i>
        </button>
    `;
    
    sessionList.appendChild(div);
    lucide.createIcons();
}

async function selectSession(id) {
    currentSessionId = id;
    localStorage.setItem('currentSessionId', id);
    
    // Update UI
    document.querySelectorAll('.session-item').forEach(item => {
        item.classList.remove('active');
        if (item.querySelector('.session-id').textContent.includes(id)) {
            item.classList.add('active');
        }
    });

    currentSessionTitle.textContent = `Chat Session`;
    currentSessionIdDisplay.textContent = id;

    await loadChatHistory(id);
}

async function loadChatHistory(id) {
    try {
        const response = await fetch(`${API_BASE_URL}/history/${id}`);
        const data = await response.json();
        
        chatMessages.innerHTML = '';
        if (data.history && data.history.length > 0) {
            data.history.forEach(msg => {
                appendMessage(msg.role === 'user' ? 'user' : 'ai', msg.content);
            });
            scrollToBottom();
            // Update theme based on last AI response
            const lastAiMsg = [...data.history].reverse().find(m => m.role === 'assistant');
            if (lastAiMsg) updateTheme(lastAiMsg.content);
        }
    } catch (err) {
        console.error('Failed to load history:', err);
    }
}

async function deleteSession(id) {
    if (!confirm('Are you sure you want to close this session? History will be lost.')) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/delete/${id}`, { method: 'DELETE' });
        if (response.ok) {
            if (currentSessionId === id) {
                currentSessionId = '';
                localStorage.removeItem('currentSessionId');
                chatMessages.innerHTML = '<div class="message ai">Session closed. Start a new one!</div>';
                currentSessionTitle.textContent = 'Select a Session';
                currentSessionIdDisplay.textContent = '';
            }
            await loadSessions();
        }
    } catch (err) {
        console.error('Delete failed:', err);
    }
}

btnNewChat.onclick = () => {
    const newId = 'session_' + Math.random().toString(36).substr(2, 9);
    selectSession(newId);
    chatMessages.innerHTML = '<div class="message ai">New session started. How can I help you?</div>';
    loadSessions(); // Refresh list to show new session placeholder if needed
};

// --- Messaging ---

async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;
    
    if (!currentSessionId) {
        const newId = 'session_' + Math.random().toString(36).substr(2, 9);
        currentSessionId = newId;
        localStorage.setItem('currentSessionId', newId);
        currentSessionIdDisplay.textContent = newId;
    }

    appendMessage('user', text);
    userInput.value = '';
    scrollToBottom();

    // Show typing indicator or just wait
    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: text
            })
        });
        
        const data = await response.json();
        if (data.success) {
            appendMessage('ai', data.response, {
                prompt: data.prompt_tokens,
                completion: data.completion_tokens,
                total: data.total_tokens
            });
            scrollToBottom();
            updateTheme(data.response);
            await loadSessions(); // Update last message in sidebar
        } else {
            appendMessage('ai', 'Error: ' + data.error);
        }
    } catch (err) {
        appendMessage('ai', 'Failed to connect to server.');
    }
}

function appendMessage(role, text, tokens = null) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    
    let contentHtml = `<span>${text}</span>`;
    
    if (tokens) {
        contentHtml += `
            <div class="message-meta">
                <div class="tokens">
                    <span class="token-tag">Prompt: ${tokens.prompt}</span>
                    <span class="token-tag">Comp: ${tokens.completion}</span>
                    <span class="token-tag">Total: ${tokens.total}</span>
                </div>
            </div>
        `;
    }
    
    div.innerHTML = contentHtml;
    chatMessages.appendChild(div);
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// --- Theme/Context Logic ---

function updateTheme(text) {
    const content = text.toLowerCase();
    const body = document.body;
    
    // Remove all theme classes
    body.classList.remove('theme-tech', 'theme-creative', 'theme-support', 'theme-warning');
    
    if (content.includes('code') || content.includes('programming') || content.includes('data')) {
        body.classList.add('theme-tech');
    } else if (content.includes('art') || content.includes('design') || content.includes('story')) {
        body.classList.add('theme-creative');
    } else if (content.includes('help') || content.includes('support') || content.includes('guide')) {
        body.classList.add('theme-support');
    } else if (content.includes('error') || content.includes('warning') || content.includes('danger')) {
        body.classList.add('theme-warning');
    } else {
        body.classList.add('theme-default');
    }
}

// Event Listeners
btnSend.onclick = sendMessage;
btnCloseCurrent.onclick = () => {
    if (currentSessionId) deleteSession(currentSessionId);
};
userInput.onkeypress = (e) => {
    if (e.key === 'Enter') sendMessage();
};

// Start the app
init();
