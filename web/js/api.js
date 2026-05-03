import { API_BASE } from './config.js';

let _token = null;

export function setToken(t) { _token = t; }
export function getToken()  { return _token; }

async function _fetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (_token) headers['Authorization'] = `Bearer ${_token}`;
    Object.assign(headers, opts.headers || {});
    const resp = await fetch(`${API_BASE}${path}`, { ...opts, headers });
    if (resp.status === 401) {
        // Token expired — clear session and reload to login
        _token = null;
        localStorage.removeItem('sr_token');
        window.location.reload();
    }
    return resp;
}

export const api = {
    login: (username, password) =>
        _fetch('/login', { method: 'POST', body: JSON.stringify({ username, password }) }),

    register: (data) =>
        _fetch('/register', { method: 'POST', body: JSON.stringify(data) }),

    wsTicket: () =>
        _fetch('/ws/ticket', { method: 'POST' }),

    contacts: () =>
        _fetch('/contacts'),

    messages: (peerId, limit = 50) =>
        _fetch(`/messages/${peerId}?limit=${limit}`),

    addContact: (username) =>
        _fetch('/contacts/add', { method: 'POST', body: JSON.stringify({ username }) }),

    searchUsers: (query) =>
        _fetch(`/users/search?query=${encodeURIComponent(query)}`),

    updateProfile: (fields) =>
        _fetch('/profile/update', { method: 'POST', body: JSON.stringify(fields) }),
};
