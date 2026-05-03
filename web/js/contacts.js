import { api }    from './api.js';
import { userId } from './auth.js';

export let contacts      = [];
export let unreadCounts  = {};    // peerId → number
export let lastMsgTimes  = {};    // peerId → Date

let _onSelect = null;

export function onContactSelect(fn) { _onSelect = fn; }

// ── Load from server ─────────────────────────────────────────────
export async function loadContacts() {
    const resp = await api.contacts();
    if (!resp.ok) return;
    contacts = await resp.json();
    renderContacts();
}

// ── Increment / clear unread badge ───────────────────────────────
export function incrementUnread(peerId) {
    unreadCounts[peerId] = (unreadCounts[peerId] || 0) + 1;
    renderContacts();
    _updateTitle();
}

export function clearUnread(peerId) {
    delete unreadCounts[peerId];
    renderContacts();
    _updateTitle();
}

export function touchLastMessage(peerId) {
    lastMsgTimes[peerId] = new Date();
    renderContacts();
}

// ── Update a contact's status from a presence event ──────────────
export function updateStatus(userId_, status) {
    const c = contacts.find(c => c.id === userId_);
    if (c) { c.status = status; renderContacts(); }
}

// ── Render ────────────────────────────────────────────────────────
export function renderContacts(filter = '') {
    const list = document.getElementById('contactList');
    if (!list) return;

    const active = document.querySelector('.contact-item.active')?.dataset.id;

    // Sort: recents mode → by last message time desc; else → unread, online, A-Z
    const sorted = [...contacts].sort((a, b) => {
        const ta = lastMsgTimes[a.id] || new Date(0);
        const tb = lastMsgTimes[b.id] || new Date(0);
        if (tb - ta !== 0) return tb - ta;               // most recent first
        const ua = unreadCounts[a.id] || 0;
        const ub = unreadCounts[b.id] || 0;
        if (ub !== ua) return ub - ua;                    // most unread first
        const ao = a.status === 'ONLINE' ? 0 : 1;
        const bo = b.status === 'ONLINE' ? 0 : 1;
        if (ao !== bo) return ao - bo;                    // online first
        return a.display_name.localeCompare(b.display_name);
    });

    const lf = filter.toLowerCase();
    const visible = lf
        ? sorted.filter(c => c.display_name.toLowerCase().includes(lf) || c.username.toLowerCase().includes(lf))
        : sorted;

    list.innerHTML = '';
    visible.forEach(c => {
        const unread  = unreadCounts[c.id] || 0;
        const lastMsg = lastMsgTimes[c.id] ? _relTime(lastMsgTimes[c.id]) : _statusLabel(c.status);
        const div = document.createElement('div');
        div.className = `contact-item${c.id === active ? ' active' : ''}`;
        div.dataset.id = c.id;
        div.setAttribute('role', 'listitem');
        div.innerHTML = `
            <div class="status-dot dot-${c.status || 'OFFLINE'}"></div>
            <div class="contact-info">
              <span class="contact-name">${_esc(c.display_name)}${c.is_bot ? ' <span style="font-size:.7rem;opacity:.6">[Bot]</span>' : ''}</span>
              <span class="contact-sub">${_esc(lastMsg)}</span>
            </div>
            ${unread ? `<span class="unread-badge" aria-label="${unread} unread">${unread}</span>` : ''}
        `;
        div.addEventListener('click', () => _onSelect && _onSelect(c));
        list.appendChild(div);
    });
}

// ── Helpers ───────────────────────────────────────────────────────
function _statusLabel(s) {
    return { ONLINE: 'Online', AWAY: 'Away', BUSY: 'Busy', INVISIBLE: 'Invisible', OFFLINE: 'Offline' }[s] || s || '';
}

function _relTime(d) {
    const diff = (Date.now() - d) / 1000;
    if (diff < 60)     return 'just now';
    if (diff < 3600)   return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400)  return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function _esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _updateTitle() {
    const total = Object.values(unreadCounts).reduce((a, b) => a + b, 0);
    document.title = total ? `(${total}) Skype Reborn` : 'Skype Reborn';
}
