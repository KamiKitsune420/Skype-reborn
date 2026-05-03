/**
 * WebRTC calling for the web client.
 *
 * Web ↔ web calls use standard WebRTC (SDP + ICE candidates forwarded
 * through the existing signalling WebSocket).  Desktop ↔ web calls are
 * not supported because the desktop client uses a proprietary UDP relay
 * with Opus — the two stacks cannot interoperate.
 *
 * We mark every outgoing CALL_INITIATE with  data.webrtc = true  so the
 * receiving side knows it should use WebRTC.  If an incoming call has no
 * such flag it came from the desktop client and we decline gracefully.
 */

import { send as wsSend } from './ws.js';
import { userId }          from './auth.js';

// ── State ─────────────────────────────────────────────────────────
let _pc          = null;   // RTCPeerConnection
let _local       = null;   // MediaStream (local mic)
let _sessionId   = null;
let _peerId      = null;
let _isCaller    = false;
let _muted       = false;
let _icePending  = [];     // candidates queued before remote desc is set
let _startTime   = null;
let _timerHandle = null;

// Caller sets this before sending the offer so we can store the full
// payload for the callee to reference (e.g. to send back the answer).
let _incomingPayload = null;

const _ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302'  },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun.cloudflare.com:3478' },
];

// ── State-change callback ─────────────────────────────────────────
// app.js registers a callback to update the UI whenever call state changes.
// Possible values: 'idle' | 'calling' | 'incoming' | 'ringing' | 'connected'
let _onState = () => {};
export function onCallState(fn) { _onState = fn; }

// ── Exports ───────────────────────────────────────────────────────

/** Call another web user.  Fails if peer is on the desktop client. */
export async function startCall(peerId) {
    if (_pc) { console.warn('Already in a call'); return; }
    _peerId    = peerId;
    _isCaller  = true;
    _sessionId = crypto.randomUUID();

    try {
        await _getLocalStream();
    } catch (err) {
        alert('Microphone access denied. Please allow microphone access to make calls.');
        _reset();
        return;
    }

    _buildPC();

    const offer = await _pc.createOffer({ offerToReceiveAudio: true });
    await _pc.setLocalDescription(offer);

    wsSend({
        type: 'CALL_INITIATE',
        payload: {
            session_id: _sessionId,
            target_id:  peerId,
            sender_id:  userId,
            data:       { webrtc: true, sdp: offer },
        },
    });

    _onState('calling');
}

/**
 * Called when the local user clicks "Answer" on an incoming call.
 * payload is the CALL_INITIATE payload stored by handleIncoming().
 */
export async function answerCall() {
    if (!_incomingPayload) return;
    const pl = _incomingPayload;

    try {
        await _getLocalStream();
    } catch {
        alert('Microphone access denied.');
        declineCall();
        return;
    }

    _buildPC();

    await _pc.setRemoteDescription(new RTCSessionDescription(pl.data.sdp));
    await _drainIcePending();

    const answer = await _pc.createAnswer();
    await _pc.setLocalDescription(answer);

    wsSend({
        type: 'CALL_ACCEPT',
        payload: {
            session_id: pl.session_id,
            target_id:  pl.sender_id,
            sender_id:  userId,
            data:       { sdp: answer },
        },
    });

    _startTimer();
    _onState('connected');
}

/**
 * Called when we receive CALL_INITIATE.
 * Returns false if the call came from a desktop client (can't answer).
 */
export function handleIncoming(payload) {
    if (!payload.data?.webrtc) {
        // Desktop client — decline immediately and inform the caller
        wsSend({
            type: 'CALL_REJECT',
            payload: {
                session_id: payload.session_id,
                target_id:  payload.sender_id,
                sender_id:  userId,
            },
        });
        return false;   // caller = desktop, we told app.js to show a notice
    }
    _incomingPayload = payload;
    _peerId    = payload.sender_id;
    _isCaller  = false;
    _sessionId = payload.session_id;
    _onState('incoming');
    return true;
}

/** Caller received CALL_ACCEPT from callee. */
export async function remoteAccepted(payload) {
    if (!_pc || !payload.data?.sdp) return;
    await _pc.setRemoteDescription(new RTCSessionDescription(payload.data.sdp));
    await _drainIcePending();
    _startTimer();
    _onState('connected');
}

/** Handle a remote ICE candidate. */
export async function addCandidate(payload) {
    if (!payload.data?.candidate) return;
    const c = new RTCIceCandidate(payload.data.candidate);
    if (_pc?.remoteDescription) {
        await _pc.addIceCandidate(c).catch(() => {});
    } else {
        _icePending.push(c);
    }
}

/** Decline an incoming call. */
export function declineCall() {
    if (_incomingPayload) {
        wsSend({
            type: 'CALL_REJECT',
            payload: {
                session_id: _incomingPayload.session_id,
                target_id:  _incomingPayload.sender_id,
                sender_id:  userId,
            },
        });
    }
    _reset();
    _onState('idle');
}

/** End the active call (works for caller and callee). */
export function hangUp() {
    if (_peerId && _sessionId) {
        wsSend({
            type: 'CALL_HANGUP',
            payload: {
                session_id: _sessionId,
                target_id:  _peerId,
                sender_id:  userId,
            },
        });
    }
    _reset();
    _onState('idle');
}

/** Toggle local microphone.  Returns new muted state. */
export function toggleMute() {
    _muted = !_muted;
    _local?.getAudioTracks().forEach(t => { t.enabled = !_muted; });
    return _muted;
}

/** Current HH:MM:SS or MM:SS string for the active call. */
export function callDuration() {
    if (!_startTime) return '0:00';
    const s = Math.floor((Date.now() - _startTime) / 1000);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    if (h > 0) return `${h}:${String(m % 60).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
    return `${m}:${String(s % 60).padStart(2,'0')}`;
}

export function isInCall() { return _pc !== null; }
export function getPeerId() { return _peerId; }

// ── Internals ─────────────────────────────────────────────────────

async function _getLocalStream() {
    _local = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
}

function _buildPC() {
    _pc = new RTCPeerConnection({ iceServers: _ICE_SERVERS });
    _local.getTracks().forEach(t => _pc.addTrack(t, _local));

    _pc.onicecandidate = ({ candidate }) => {
        if (candidate) {
            wsSend({
                type: 'CALL_CANDIDATE',
                payload: {
                    session_id: _sessionId,
                    target_id:  _peerId,
                    sender_id:  userId,
                    data:       { candidate },
                },
            });
        }
    };

    _pc.ontrack = ({ streams }) => {
        const audio = document.getElementById('remoteAudio');
        if (audio) audio.srcObject = streams[0];
    };

    _pc.onconnectionstatechange = () => {
        const s = _pc?.connectionState;
        if (s === 'connected') {
            _onState('connected');
        } else if (s === 'failed' || s === 'disconnected' || s === 'closed') {
            _reset();
            _onState('idle');
        }
    };

    _pc.oniceconnectionstatechange = () => {
        if (_pc?.iceConnectionState === 'checking') _onState('ringing');
    };
}

async function _drainIcePending() {
    for (const c of _icePending) {
        await _pc.addIceCandidate(c).catch(() => {});
    }
    _icePending = [];
}

function _startTimer() {
    _startTime = Date.now();
    clearInterval(_timerHandle);
    _timerHandle = setInterval(() => _onState('connected'), 1000);
}

function _reset() {
    clearInterval(_timerHandle);
    _timerHandle = null;
    _startTime   = null;
    _local?.getTracks().forEach(t => t.stop());
    _local = null;
    _pc?.close();
    _pc = null;
    const audio = document.getElementById('remoteAudio');
    if (audio) audio.srcObject = null;
    _peerId          = null;
    _sessionId       = null;
    _isCaller        = false;
    _muted           = false;
    _icePending      = [];
    _incomingPayload = null;
}
