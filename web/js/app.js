import { api, setToken }                          from './api.js';
import { on as wsOn, send as wsSend, connect as wsConnect } from './ws.js';
import { login, register, logout, restoreSession,
         userId, username }                        from './auth.js';
import { loadContacts, renderContacts, contacts,
         onContactSelect, incrementUnread,
         clearUnread, touchLastMessage,
         updateStatus }                            from './contacts.js';
import { openConversation, appendMessage,
         applyReaction, markDelivered, markRead,
         showTyping, sendMessage, cancelReply,
         activePeerId }                            from './messages.js';
import { showApp, showLogin, showChat,
         setMyProfile, setStatus, setChatHeader,
         setAuthStatus, toast, browserNotify,
         requestNotificationPermission }           from './ui.js';

// ── Boot ──────────────────────────────────────────────────────────
async function boot() {
    if (restoreSession()) {
        await startSession();
    }
    // else: login screen is shown by default (visible in HTML)
}

async function startSession() {
    showApp();
    setMyProfile(username, 'ONLINE');
    await requestNotificationPermission();
    _bindWS();
    await wsConnect();
    await loadContacts();
}

// ── Auth form wiring ──────────────────────────────────────────────
document.getElementById('loginBtn').addEventListener('click', async () => {
    const u = document.getElementById('username').value.trim();
    const p = document.getElementById('password').value.trim();
    const r = document.getElementById('rememberMe').checked;
    if (!u || !p) { setAuthStatus('Please fill in all fields.', true); return; }
    setAuthStatus('Signing in…');
    document.getElementById('loginBtn').disabled = true;
    try {
        await login(u, p, r);
        await startSession();
    } catch (e) {
        setAuthStatus(e.message, true);
        document.getElementById('loginBtn').disabled = false;
    }
});

document.getElementById('toRegisterBtn').addEventListener('click', () => {
    document.getElementById('loginForm').classList.add('hidden');
    document.getElementById('registerForm').classList.remove('hidden');
    setAuthStatus('');
});
document.getElementById('toLoginBtn').addEventListener('click', () => {
    document.getElementById('registerForm').classList.add('hidden');
    document.getElementById('loginForm').classList.remove('hidden');
    setAuthStatus('');
});

document.getElementById('doRegisterBtn').addEventListener('click', async () => {
    const fields = {
        username:   document.getElementById('reg_user').value.trim(),
        password:   document.getElementById('reg_pass').value.trim(),
        email:      document.getElementById('reg_email').value.trim(),
        first_name: document.getElementById('reg_fname').value.trim(),
        last_name:  document.getElementById('reg_lname').value.trim(),
    };
    if (Object.values(fields).some(v => !v)) { setAuthStatus('All fields are required.', true); return; }
    setAuthStatus('Creating account…');
    document.getElementById('doRegisterBtn').disabled = true;
    try {
        await register(fields);
        setAuthStatus('Account created! You can now sign in.', false);
        document.getElementById('registerForm').classList.add('hidden');
        document.getElementById('loginForm').classList.remove('hidden');
    } catch (e) {
        setAuthStatus(e.message, true);
    } finally {
        document.getElementById('doRegisterBtn').disabled = false;
    }
});

// ── Logout ────────────────────────────────────────────────────────
document.getElementById('logoutBtn').addEventListener('click', logout);

// ── Status change ─────────────────────────────────────────────────
document.getElementById('statusDropBtn').addEventListener('click', () => {
    document.getElementById('statusMenu').classList.toggle('hidden');
});
document.getElementById('statusMenu').addEventListener('click', e => {
    const status = e.target.dataset.status;
    if (!status) return;
    wsSend({ type: 'PRESENCE_UPDATE', payload: { user_id: userId, status } });
    setStatus(status);
    document.getElementById('statusMenu').classList.add('hidden');
});

// ── Contact selection ─────────────────────────────────────────────
onContactSelect(async (contact) => {
    setChatHeader(contact);
    showChat();
    clearUnread(contact.id);
    await openConversation(contact);
});

// ── Search ────────────────────────────────────────────────────────
document.getElementById('searchInput').addEventListener('input', e => {
    renderContacts(e.target.value);
});

// ── Message input ─────────────────────────────────────────────────
const msgInput = document.getElementById('messageInput');
const sendBtn  = document.getElementById('sendBtn');

msgInput.addEventListener('input', () => {
    sendBtn.disabled = !msgInput.value.trim();
    // Auto-resize
    msgInput.style.height = 'auto';
    msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + 'px';
    // Typing indicator
    _handleTyping();
});

msgInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        _doSend();
    }
});

sendBtn.addEventListener('click', _doSend);

function _doSend() {
    const text = msgInput.value.trim();
    if (!text || !activePeerId) return;
    sendMessage(text);
    // Optimistic append
    appendMessage({
        sender_id: userId, conversation_id: activePeerId,
        content: text, timestamp: new Date().toISOString(),
    });
    msgInput.value = '';
    msgInput.style.height = 'auto';
    sendBtn.disabled = true;
}

// ── Reply bar ─────────────────────────────────────────────────────
document.getElementById('cancelReplyBtn').addEventListener('click', () => cancelReply());

// ── Typing throttle ───────────────────────────────────────────────
let _typingTimer = null;
function _handleTyping() {
    if (!activePeerId) return;
    if (!_typingTimer) {
        wsSend({ type: 'CHAT_TYPING', payload: { conversation_id: activePeerId, user_id: userId, is_typing: true } });
    }
    clearTimeout(_typingTimer);
    _typingTimer = setTimeout(() => {
        wsSend({ type: 'CHAT_TYPING', payload: { conversation_id: activePeerId, user_id: userId, is_typing: false } });
        _typingTimer = null;
    }, 3000);
}

// ── Call button (placeholder) ─────────────────────────────────────
document.getElementById('callBtn').addEventListener('click', () => {
    toast('Web calling coming soon. Use the desktop client to call.');
});

// ── WebSocket event handling ──────────────────────────────────────
function _bindWS() {
    wsOn('CHAT_RECEIVE', payload => {
        const peerId = payload.sender_id;
        const content = payload.content || '';

        // Reaction message
        const reactMatch = content.match(/^\[react:(.+)\]$/);
        if (reactMatch) {
            const senderContact = contacts.find(c => c.id === peerId);
            const name = senderContact?.display_name || 'Someone';
            if (activePeerId === peerId) applyReaction(reactMatch[1], name);
            toast(`${name} reacted to your message`);
            browserNotify('Skype Reborn', `${name} reacted to your message`);
            return;
        }

        touchLastMessage(peerId);

        if (activePeerId === peerId) {
            appendMessage(payload);
            // Send read receipt
            wsSend({ type: 'CHAT_ACK', payload: { peer_id: peerId, reader_id: userId, status: 'read' } });
        } else {
            incrementUnread(peerId);
            const senderContact = contacts.find(c => c.id === peerId);
            const name = senderContact?.display_name || 'Someone';
            toast(`${name}: ${content.substring(0, 60)}`);
            browserNotify(`Skype Reborn — ${name}`, content.substring(0, 120));
        }
    });

    wsOn('CHAT_ACK', payload => {
        if (payload.status === 'delivered') markDelivered();
        else if (payload.status === 'read')  markRead();
    });

    wsOn('CHAT_TYPING', payload => {
        if (payload.user_id !== userId && activePeerId === payload.user_id) {
            showTyping(payload.is_typing);
        }
    });

    wsOn('PRESENCE_BROADCAST', payload => {
        updateStatus(payload.user_id, payload.status);
    });

    wsOn('_connected',    () => toast('Connected'));
    wsOn('_disconnected', () => toast('Disconnected — reconnecting…'));
}

// ── Start ─────────────────────────────────────────────────────────
boot();
