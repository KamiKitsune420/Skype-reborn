// Derive API and WebSocket base URLs from the page's own origin.
// Works whether accessed via localhost, LAN IP, or the live server —
// no hardcoded host or port needed.
export const API_BASE = window.location.origin;
export const WS_BASE  = API_BASE.replace(/^http/, 'ws');
