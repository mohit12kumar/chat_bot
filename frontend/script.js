const API_BASE_URL = '';
let currentSessionId = '';

// DOM Elements
const sessionList = document.getElementById('session-list');
const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const btnSend = document.getElementById('btn-send');
const btnNewChat = document.getElementById('btn-new-chat');
const currentSessionTitle = document.getElementById('current-session-title');
const currentSessionIdDisplay = document.getElementById('current-session-id');

// --- Initialization ---
async function init() {
    await loadSessions();
    
    // Automatically start a new session on refresh
    const newId = 'session_' + Math.random().toString(36).substr(2, 9);
    selectSession(newId);
    chatMessages.innerHTML = '<div class="message ai">New session started. How can I help you?</div>';
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
        <div class="session-actions" style="position: relative;">
            <button class="btn-close-session" onclick="event.stopPropagation(); toggleDropdown('${id}')" title="Options">
                <i data-lucide="more-vertical"></i>
            </button>
            <div id="dropdown-${id}" class="session-dropdown" style="display: none; position: absolute; right: 0; top: 100%; background: rgba(30,30,46,0.95); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 4px; z-index: 1000; min-width: 100px; box-shadow: 0 4px 6px rgba(0,0,0,0.5);">
                <button onclick="event.stopPropagation(); actualDeleteSession('${id}')" style="display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; background: transparent; border: none; color: #ff4d4f; cursor: pointer; text-align: left; border-radius: 4px; font-family: inherit;">
                    <i data-lucide="trash-2" style="width: 14px; height: 14px;"></i> Delete
                </button>
                <button onclick="event.stopPropagation(); archiveSession('${id}')" style="display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 8px; background: transparent; border: none; color: #fff; cursor: pointer; text-align: left; border-radius: 4px; font-family: inherit;">
                    <i data-lucide="archive" style="width: 14px; height: 14px;"></i> Archive
                </button>
            </div>
        </div>
    `;
    
    sessionList.appendChild(div);
    lucide.createIcons();
}

function toggleDropdown(id) {
    document.querySelectorAll('.session-dropdown').forEach(el => {
        if (el.id !== `dropdown-${id}`) el.style.display = 'none';
    });
    const headerDropdown = document.getElementById('header-dropdown');
    if (headerDropdown) headerDropdown.style.display = 'none';
    
    const dropdown = document.getElementById(`dropdown-${id}`);
    if (dropdown) dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
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

async function deleteSession(id, reason = 'user') {
    // Only affect the UI if the user is closing the currently active session
    if (currentSessionId === id) {
        let closingMsg = '';
        if (reason === 'system') {
            closingMsg = 'System message: your token are fully used, closing session.';
        } else {
            closingMsg = 'your session ended';
        }
        
        appendMessage('ai', closingMsg);

        // Save this closing message to the database
        fetch(`${API_BASE_URL}/system-message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: id, message: closingMsg })
        }).catch(err => console.error('Failed to save closing message:', err));
        
        // Remove from current active view
        currentSessionId = '';
        localStorage.removeItem('currentSessionId');
        currentSessionTitle.textContent = 'Select a Session';
        currentSessionIdDisplay.textContent = '';
        
        // Update sidebar to un-highlight the active item
        document.querySelectorAll('.session-item').forEach(item => {
            item.classList.remove('active');
        });
    } else {
        alert("This session is saved in the database and can only be deleted by Postman commands.");
    }
}

btnNewChat.onclick = () => {
    const newId = 'session_' + Math.random().toString(36).substr(2, 9);
    selectSession(newId);
    chatMessages.innerHTML = '<div class="message ai">New session started. How can I help you?</div>';
    loadSessions(); // Refresh list to show new session placeholder if needed
};

// --- Session Search Logic ---
const sessionSearch = document.getElementById('session-search');
if (sessionSearch) {
    sessionSearch.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        const items = document.querySelectorAll('.session-item');
        items.forEach(item => {
            const sessionIdText = item.querySelector('.session-id').textContent.toLowerCase();
            if (sessionIdText.includes(query)) {
                item.style.display = 'flex';
            } else {
                item.style.display = 'none';
            }
        });
    });
}

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

    // Prepare AI message bubble for streaming
    const aiMessageDiv = appendMessage('ai', '');
    const aiSpan = aiMessageDiv.querySelector('.msg-content');

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: text
            })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullText = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.text) {
                        fullText += data.text;
                        aiSpan.innerHTML = marked.parse(fullText);
                        scrollToBottom();
                    }
                    if (data.done) {
                        updateTheme(data.full_content || fullText);
                        
                        // Render Token Info at the end
                        if (data.usage) {
                            const metaDiv = document.createElement('div');
                            metaDiv.className = 'message-meta';
                            metaDiv.innerHTML = `
                                <div class="tokens">
                                    <span class="token-tag">Prompt: ${data.usage.prompt_tokens}</span>
                                    <span class="token-tag">Comp: ${data.usage.completion_tokens}</span>
                                    <span class="token-tag">Total: ${data.usage.total_tokens}</span>
                                </div>
                            `;
                            aiMessageDiv.appendChild(metaDiv);
                            
                            // Check if tokens are "fully used" (e.g., hit a max limit)
                            if (data.usage.total_tokens >= 4000) {
                                deleteSession(currentSessionId, 'system');
                            }
                        }

                        await loadSessions(); 
                    }
                } catch (e) {
                    console.error('Error parsing stream chunk:', e);
                }
            }
        }
    } catch (err) {
        aiSpan.textContent = 'Failed to connect to server.';
    }
}

function appendMessage(role, text, tokens = null) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    
    // Parse markdown for AI and system, treat user text as plain
    const parsedText = (role === 'ai' || role === 'system') ? marked.parse(text) : text;
    let contentHtml = `<div class="msg-content">${parsedText}</div>`;
    
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
    return div;
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

const btnDeleteCurrent = document.getElementById('btn-delete-current');
const btnArchiveCurrent = document.getElementById('btn-archive-current');

if (btnDeleteCurrent) btnDeleteCurrent.onclick = () => { 
    if (currentSessionId) actualDeleteSession(currentSessionId); 
};
if (btnArchiveCurrent) btnArchiveCurrent.onclick = () => { 
    if (currentSessionId) archiveSession(currentSessionId); 
};

// Close dropdowns on outside click
document.addEventListener('click', () => {
    const headerDropdown = document.getElementById('header-dropdown');
    if (headerDropdown) headerDropdown.style.display = 'none';
    document.querySelectorAll('.session-dropdown').forEach(el => el.style.display = 'none');
});

// Event Listeners
btnSend.onclick = sendMessage;

userInput.onkeypress = (e) => {
    if (e.key === 'Enter') sendMessage();
};

async function actualDeleteSession(id) {
    if (!confirm('Are you sure you want to completely delete this session? This cannot be undone.')) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/delete/${id}`, { method: 'DELETE' });
        if (response.ok) {
            if (currentSessionId === id) {
                currentSessionId = '';
                localStorage.removeItem('currentSessionId');
                chatMessages.innerHTML = '<div class="message ai">Session deleted. Start a new one!</div>';
                currentSessionTitle.textContent = 'Select a Session';
                currentSessionIdDisplay.textContent = '';
            }
            await loadSessions();
        }
    } catch (err) {
        console.error('Delete failed:', err);
    }
}

async function archiveSession(id) {
    if (!confirm('Are you sure you want to archive this session?')) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/archive/${id}`, { method: 'POST' });
        if (response.ok) {
            if (currentSessionId === id) {
                currentSessionId = '';
                localStorage.removeItem('currentSessionId');
                chatMessages.innerHTML = '<div class="message ai">Session archived. Start a new one!</div>';
                currentSessionTitle.textContent = 'Select a Session';
                currentSessionIdDisplay.textContent = '';
            }
            await loadSessions();
        }
    } catch (err) {
        console.error('Archive failed:', err);
    }
}

// Start the app
init();
