import { WS_BASE } from './config.js';
import { api }     from './api.js';

let _ws       = null;
let _retryMs  = 1000;
let _handlers = {};   // { messageType: [callback, ...] }

export function on(type, handler) {
    (_handlers[type] = _handlers[type] || []).push(handler);
}

function _dispatch(envelope) {
    (_handlers[envelope.type] || []).forEach(h => {
        try { h(envelope.payload); } catch (e) { console.error('WS handler error', e); }
    });
}

export async function connect() {
    const resp = await api.wsTicket();
    if (!resp.ok) { console.warn('Could not get WS ticket'); return; }
    const { ticket } = await resp.json();

    _ws = new WebSocket(`${WS_BASE}/ws/${ticket}`);

    _ws.onopen = () => {
        console.info('WebSocket connected');
        _retryMs = 1000;
        _dispatch({ type: '_connected', payload: {} });
    };

    _ws.onmessage = (ev) => {
        try { _dispatch(JSON.parse(ev.data)); } catch (e) { console.error('Bad WS message', e); }
    };

    _ws.onclose = () => {
        console.warn(`WebSocket closed — retrying in ${_retryMs}ms`);
        _dispatch({ type: '_disconnected', payload: {} });
        setTimeout(() => connect(), _retryMs);
        _retryMs = Math.min(_retryMs * 2, 30_000);
    };

    _ws.onerror = (e) => console.error('WebSocket error', e);
}

export function send(obj) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
        _ws.send(JSON.stringify(obj));
    }
}
