import { api }    from './api.js';
import { send }   from './ws.js';
import { userId } from './auth.js';
import { touchLastMessage } from './contacts.js';

export let activePeerId   = null;
export let activePeerName = null;
let _replyTo = null;   // { sender, content } | null

const _REACTION_TEXT = {
    '👍':'thumbed this', '🤣':'laughed at this', '😂':'laughed at this',
    '❤️':'loved this',  '😮':'was wowed by this','😢':'cried at this',
    '😡':'disliked this','🔥':'found this fire',  '🎉':'celebrated this',
    '😊':'liked this',
};

// ── Open conversation ─────────────────────────────────────────────
export async function openConversation(contact) {
    activePeerId   = contact.id;
    activePeerName = contact.display_name;
    _replyTo = null;
    _hideReplyBar();

    const history = document.getElementById('messageHistory');
    history.innerHTML = '<div style="text-align:center;color:#aaa;padding:2rem">Loading…</div>';

    const resp = await api.messages(contact.id, 50);
    history.innerHTML = '';

    if (!resp.ok) { history.innerHTML = '<div style="color:red;padding:1rem">Failed to load messages</div>'; return; }

    const msgs = await resp.json();
    let lastDay = null;
    msgs.forEach(m => {
        const dt = _parseUTC(m.timestamp);
        const day = dt.toDateString();
        if (day !== lastDay) {
            history.appendChild(_dayDivider(dt));
            lastDay = day;
        }
        history.appendChild(_buildBubble(m));
    });

    _scrollBottom();

    // Mark as read
    send({
        type: 'CHAT_ACK',
        payload: { peer_id: contact.id, reader_id: userId, status: 'read' },
    });
}

// ── Append an incoming or sent message ───────────────────────────
export function appendMessage(msg, scroll = true) {
    const history = document.getElementById('messageHistory');
    if (!history) return;
    history.appendChild(_buildBubble(msg));
    if (scroll) _scrollBottom();
    touchLastMessage(msg.sender_id === userId ? msg.conversation_id : msg.sender_id);
}

// ── Apply a reaction (from peer) ─────────────────────────────────
export function applyReaction(emoji, senderName) {
    const history = document.getElementById('messageHistory');
    if (!history) return;
    // Find last bubble sent by the local user
    const bubbles = history.querySelectorAll('.msg-wrapper.sent');
    if (!bubbles.length) return;
    const last  = bubbles[bubbles.length - 1];
    const react = last.querySelector('.msg-reactions') || (() => {
        const d = document.createElement('div'); d.className = 'msg-reactions';
        last.appendChild(d); return d;
    })();
    const verb = _REACTION_TEXT[emoji] || `reacted with ${emoji}`;
    react.textContent += (react.textContent ? '  ' : '') + `${emoji} ${senderName} ${verb}`;
}

// ── Mark all sent messages delivered / read ───────────────────────
export function markDelivered() { _updateReceipts(false); }
export function markRead()      { _updateReceipts(true);  }

function _updateReceipts(isRead) {
    document.querySelectorAll('.msg-receipt').forEach(el => {
        const current = el.dataset.state;
        if (current === 'read') return;
        if (isRead) {
            el.textContent = '✓✓ Read'; el.dataset.state = 'read'; el.classList.add('read');
        } else if (current !== 'delivered') {
            el.textContent = '✓✓'; el.dataset.state = 'delivered';
        }
    });
}

// ── Typing indicator ─────────────────────────────────────────────
export function showTyping(show) {
    const el = document.getElementById('typingIndicator');
    if (el) el.classList.toggle('hidden', !show);
}

// ── Send ──────────────────────────────────────────────────────────
export function sendMessage(content) {
    if (!content || !activePeerId) return;
    let final = content;
    if (_replyTo) {
        const orig = (_replyTo.content || '').substring(0, 120);
        final = `[Reply to ${_replyTo.sender}: ${orig}]\n${content}`;
        _hideReplyBar();
        _replyTo = null;
    }
    send({
        type: 'CHAT_SEND',
        payload: { conversation_id: activePeerId, sender_id: userId, content: final },
    });
    touchLastMessage(activePeerId);
}

// ── Reply bar ─────────────────────────────────────────────────────
export function setReply(sender, content) {
    _replyTo = { sender, content };
    const bar  = document.getElementById('replyBar');
    const lbl  = document.getElementById('replyLabel');
    if (bar && lbl) {
        const preview = content.substring(0, 80) + (content.length > 80 ? '…' : '');
        lbl.textContent = `↩ Replying to ${sender}: "${preview}"`;
        bar.classList.remove('hidden');
    }
}
export function cancelReply() {
    _replyTo = null;
    _hideReplyBar();
}
function _hideReplyBar() {
    document.getElementById('replyBar')?.classList.add('hidden');
}

// ── Build a message bubble ────────────────────────────────────────
function _buildBubble(m) {
    const isMine = m.sender_id === userId;
    const dt     = _parseUTC(m.timestamp);
    const content = m.content || '';

    // Detect special formats
    const replyMatch = content.match(/^\[Reply to (.+?): ([\s\S]+?)\]\n([\s\S]+)$/);
    const reactMatch = !replyMatch && content.match(/^\[react:(.+)\]$/);

    if (reactMatch) {
        // Reaction message — handled externally, skip rendering as bubble
        return document.createDocumentFragment();
    }

    const wrap = document.createElement('div');
    wrap.className = `msg-wrapper ${isMine ? 'sent' : 'recv'}`;

    // Sender name for received messages
    if (!isMine) {
        const sn = document.createElement('div');
        sn.className = 'msg-sender';
        sn.textContent = m.sender_name || activePeerName || '';
        wrap.appendChild(sn);
    }

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.addEventListener('dblclick', () => {
        const s = isMine ? 'You' : (activePeerName || '');
        setReply(s, replyMatch ? replyMatch[3] : content);
        document.getElementById('messageInput')?.focus();
    });

    // Reply quote
    if (replyMatch) {
        const quote = document.createElement('div');
        quote.className = 'msg-reply-quote';
        quote.textContent = `${replyMatch[1]}: "${replyMatch[2].substring(0, 80)}"`;
        bubble.appendChild(quote);
        const text = document.createElement('div');
        text.textContent = replyMatch[3];
        bubble.appendChild(text);
    } else {
        bubble.textContent = content;
    }

    wrap.appendChild(bubble);

    // Reactions
    const reactDiv = document.createElement('div');
    reactDiv.className = 'msg-reactions';
    wrap.appendChild(reactDiv);

    // Meta row
    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    const timeEl = document.createElement('span');
    timeEl.className = 'msg-time';
    timeEl.textContent = _formatTime(dt);
    timeEl.title = dt.toLocaleString();
    meta.appendChild(timeEl);

    if (isMine) {
        const receipt = document.createElement('span');
        receipt.className = 'msg-receipt';
        if (m.read_at) {
            receipt.textContent = '✓✓ Read'; receipt.dataset.state = 'read'; receipt.classList.add('read');
        } else if (m.delivered_at) {
            receipt.textContent = '✓✓'; receipt.dataset.state = 'delivered';
        } else {
            receipt.textContent = '✓'; receipt.dataset.state = 'sent';
        }
        meta.appendChild(receipt);
    }

    wrap.appendChild(meta);
    return wrap;
}

function _dayDivider(dt) {
    const div = document.createElement('div');
    div.className = 'day-divider';
    const today = new Date().toDateString();
    div.textContent = dt.toDateString() === today
        ? 'Today'
        : dt.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
    return div;
}

function _scrollBottom() {
    const h = document.getElementById('messageHistory');
    if (h) h.scrollTop = h.scrollHeight;
}

// ── Time helpers ──────────────────────────────────────────────────
function _parseUTC(str) {
    if (!str) return new Date();
    // SQLite stores naive UTC — add Z so JS Date parses it as UTC
    const s = String(str).replace(' ', 'T');
    return new Date(s.includes('Z') || /[+-]\d{2}:/.test(s) ? s : s + 'Z');
}

function _formatTime(dt) {
    const diff = (Date.now() - dt) / 1000;
    if (diff < 60)    return 'just now';
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (diff < 604800) return dt.toLocaleDateString([], { weekday: 'short' }) + ' '
                            + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return dt.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' '
         + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
