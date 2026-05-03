// ── Panel switching ───────────────────────────────────────────────
export function showApp()   { toggle('loginScreen', false); toggle('app', true); }
export function showLogin() { toggle('loginScreen', true);  toggle('app', false); }
export function showChat()  { toggle('welcomePane', false); toggle('chatPane', true); }

export function setMyProfile(uname, status = 'ONLINE') {
    setText('myUsername', uname);
    const avatar = document.getElementById('myAvatar');
    if (avatar) avatar.textContent = uname[0].toUpperCase();
    setStatus(status);
}

export function setStatus(status) {
    const el = document.getElementById('myStatus');
    if (!el) return;
    const labels = { ONLINE:'Online', AWAY:'Away', BUSY:'Busy', INVISIBLE:'Invisible', OFFLINE:'Offline' };
    el.textContent = labels[status] || status;
    el.className = 'status-text ' + status.toLowerCase();
}

export function setChatHeader(contact) {
    const av  = document.getElementById('chatAvatar');
    const nm  = document.getElementById('chatName');
    if (av) av.textContent = (contact.display_name || '?')[0].toUpperCase();
    if (nm) nm.textContent  = contact.display_name || '';
    // Mark the active contact in the list
    document.querySelectorAll('.contact-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === contact.id);
    });
}

// ── Auth status ───────────────────────────────────────────────────
export function setAuthStatus(msg, isError = false) {
    const el = document.getElementById('authStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'auth-status ' + (isError ? 'error' : 'success');
}

// ── Toast notifications ───────────────────────────────────────────
export function toast(message, durationMs = 4000) {
    const c = document.getElementById('toastContainer');
    if (!c) return;
    const t = document.createElement('div');
    t.className = 'toast'; t.textContent = message;
    c.appendChild(t);
    setTimeout(() => t.remove(), durationMs);
}

// ── Browser notification (when window not focused) ────────────────
let _notifPermission = 'default';
export async function requestNotificationPermission() {
    if ('Notification' in window) {
        _notifPermission = await Notification.requestPermission();
    }
}
export function browserNotify(title, body, icon = '/web/favicon.ico') {
    if (_notifPermission !== 'granted' || document.hasFocus()) return;
    try { new Notification(title, { body, icon }); } catch (_) { /* ignored */ }
}

// ── Helpers ───────────────────────────────────────────────────────
function toggle(id, visible) {
    document.getElementById(id)?.classList.toggle('hidden', !visible);
}
function setText(id, text) {
    const el = document.getElementById(id); if (el) el.textContent = text;
}
