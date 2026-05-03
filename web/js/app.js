import { api, setToken }                              from './api.js';
import { on as wsOn, send as wsSend, connect as wsConnect } from './ws.js';
import { login, register, logout, restoreSession,
         userId, username }                          from './auth.js';
import { loadContacts, renderContacts, contacts,
         onContactSelect, incrementUnread,
         clearUnread, touchLastMessage,
         updateStatus }                              from './contacts.js';
import { openConversation, appendMessage,
         applyReaction, markDelivered, markRead,
         showTyping, sendMessage, cancelReply,
         activePeerId }                              from './messages.js';
import { showApp, showLogin, showChat,
         setMyProfile, setStatus, setChatHeader,
         setAuthStatus, toast, browserNotify,
         requestNotificationPermission }             from './ui.js';
import * as calls                                    from './calls.js';

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

// ── Call button ───────────────────────────────────────────────────
document.getElementById('callBtn').addEventListener('click', async () => {
    if (!activePeerId) return;
    if (calls.isInCall()) { toast('You are already in a call.'); return; }
    const peer = contacts.find(c => c.id === activePeerId);
    _showActiveCall(peer?.display_name || 'Contact', 'Calling…');
    await calls.startCall(activePeerId);
});

document.getElementById('answerBtn').addEventListener('click', async () => {
    document.getElementById('incomingCallModal').classList.add('hidden');
    const name = document.getElementById('incomingName').textContent;
    _showActiveCall(name, 'Connecting…');
    await calls.answerCall();
});

document.getElementById('declineBtn').addEventListener('click', () => {
    document.getElementById('incomingCallModal').classList.add('hidden');
    calls.declineCall();
});

document.getElementById('hangupBtn').addEventListener('click', () => {
    calls.hangUp();
});

document.getElementById('muteBtn').addEventListener('click', function() {
    const muted = calls.toggleMute();
    this.textContent = muted ? '🔇 Unmute' : '🎤 Mute';
    this.classList.toggle('muted', muted);
});

// ── Call state machine ────────────────────────────────────────────
calls.onCallState(state => {
    const overlay  = document.getElementById('activeCallOverlay');
    const statusEl = document.getElementById('activeCallStatus');
    const timerEl  = document.getElementById('callTimer');

    if (state === 'idle') {
        overlay.classList.add('hidden');
        document.getElementById('incomingCallModal').classList.add('hidden');
        timerEl.textContent = '';
        document.getElementById('muteBtn').textContent = '🎤 Mute';
        document.getElementById('muteBtn').classList.remove('muted');
    } else if (state === 'calling') {
        if (statusEl) statusEl.textContent = 'Calling…';
    } else if (state === 'ringing') {
        if (statusEl) statusEl.textContent = 'Ringing…';
    } else if (state === 'connected') {
        if (statusEl) statusEl.textContent = 'In call';
        if (timerEl)  timerEl.textContent  = calls.callDuration();
    }
});

function _showActiveCall(peerName, statusText) {
    const av  = document.getElementById('activeCallAvatar');
    const nm  = document.getElementById('activeCallName');
    const st  = document.getElementById('activeCallStatus');
    if (av) av.textContent = (peerName || '?')[0].toUpperCase();
    if (nm) nm.textContent = peerName || '—';
    if (st) st.textContent = statusText;
    document.getElementById('activeCallOverlay').classList.remove('hidden');
}

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

    // ── Call signalling ───────────────────────────────────────────
    wsOn('CALL_INITIATE', payload => {
        if (calls.isInCall()) {
            // Already busy — reject immediately
            wsSend({ type: 'CALL_REJECT',
                     payload: { session_id: payload.session_id,
                                target_id: payload.sender_id, sender_id: userId } });
            return;
        }
        const accepted = calls.handleIncoming(payload);
        if (!accepted) {
            toast('Desktop call received — not supported in the web client.');
            return;
        }
        // Show incoming call UI
        const peer = contacts.find(c => c.id === payload.sender_id);
        const name = peer?.display_name || 'Someone';
        const av   = document.getElementById('incomingAvatar');
        const nm   = document.getElementById('incomingName');
        if (av) av.textContent = name[0].toUpperCase();
        if (nm) nm.textContent = name;
        document.getElementById('incomingCallModal').classList.remove('hidden');
        browserNotify('Skype Reborn — Incoming Call', `${name} is calling you`);
    });

    wsOn('CALL_ACCEPT', async payload => {
        await calls.remoteAccepted(payload);
        const name = document.getElementById('activeCallName')?.textContent || '—';
        _showActiveCall(name, 'In call');
    });

    wsOn('CALL_REJECT', () => {
        calls.hangUp();
        toast('Call declined.');
    });

    wsOn('CALL_HANGUP', () => {
        calls.hangUp();
        toast('Call ended.');
    });

    wsOn('CALL_CANDIDATE', async payload => {
        await calls.addCandidate(payload);
    });

    wsOn('_connected',    () => toast('Connected'));
    wsOn('_disconnected', () => {
        if (calls.isInCall()) calls.hangUp();
        toast('Disconnected — reconnecting…');
    });
}

// ── Start ─────────────────────────────────────────────────────────
boot();
