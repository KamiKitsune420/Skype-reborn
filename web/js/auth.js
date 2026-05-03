import { api, setToken } from './api.js';
import { connect as wsConnect } from './ws.js';

export let userId   = null;
export let username = null;

// ── Restore session from localStorage ────────────────────────────
export function restoreSession() {
    const t  = localStorage.getItem('sr_token');
    const id = localStorage.getItem('sr_user_id');
    const u  = localStorage.getItem('sr_username');
    if (t && id && u) {
        setToken(t);
        userId   = id;
        username = u;
        return true;
    }
    return false;
}

function _persist(token, id, uname, remember) {
    setToken(token);
    userId   = id;
    username = uname;
    if (remember) {
        localStorage.setItem('sr_token',    token);
        localStorage.setItem('sr_user_id',  id);
        localStorage.setItem('sr_username', uname);
    }
}

// ── Login ─────────────────────────────────────────────────────────
export async function login(uname, pass, remember) {
    const resp = await api.login(uname, pass);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Login failed (${resp.status})`);
    }
    const data = await resp.json();
    _persist(data.token, data.user_id, uname, remember);
    await wsConnect();
}

// ── Register ──────────────────────────────────────────────────────
export async function register(fields) {
    const resp = await api.register(fields);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Registration failed (${resp.status})`);
    }
}

// ── Logout ────────────────────────────────────────────────────────
export function logout() {
    localStorage.removeItem('sr_token');
    localStorage.removeItem('sr_user_id');
    localStorage.removeItem('sr_username');
    setToken(null);
    userId   = null;
    username = null;
    window.location.reload();
}
