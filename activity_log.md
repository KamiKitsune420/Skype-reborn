# Activity Log

| Action | Status | Notes |
| :--- | :--- | :--- |
| Created project directory structure | Success | Created server, client, shared, bots, docs, scripts, tests directories |
| Initialized activity log | Success | Created activity_log.md |
| Wrote docs/architecture.md | Success | Defined high-level system design and components |
| Wrote docs/protocol.md | Success | Defined signaling and media protocol specifications |
| Implemented shared/models.py | Success | Created Pydantic models for protocol |
| Tested shared models | Success | Verified serialization/deserialization |
| Implemented server minimal vertical slice | Success | Auth endpoints and basic WS gateway |
| Tested server auth | Success | Verified register and login integration |
| Implemented client basic structure | Success | Created UI and network layers |
| Integrated wxasync | Success | Enabled asyncio in wxPython client |
| Implemented WS messaging | Success | Enabled real-time chat in UI |
| Added basic message history | Success | Messages display in chat area |
| Implemented Voice Relay Server | Success | UDP server for audio packets |
| Integrated Audio Engine | Success | Capture and playback via sounddevice |
| Implemented Echo Service | Success | Audio loopback with delay |
| Created Bot SDK | Success | Async SDK for creating bots |
| Implemented Echo Bot | Success | Responds to messages with echo |
| Implemented File Transfer Endpoints | Success | Chunked upload and download |
| Fixed server/main.py structure | Success | Corrected imports and duplicate app instances |
| Created Headless Client | Success | CLI tool for debugging |
| Wrote README.md and requirements.txt | Success | Documentation and dependency list |
| Completed initial implementation | Success | Ready for testing and usage |
| Implemented Contact Management | Success | Added DB model and API endpoints for friends |
| Implemented Message History | Success | DB storage for all messages, load on chat select |
| Completed Call Signaling | Success | Added Initiate/Accept/Reject flow via WebSockets |
| Implemented Presence Broadcast | Success | Notifies all connected users on status changes |
| Implemented Advanced Echo Service | Success | Full sequence: Intro -> Beep -> Record -> Beep -> Playback -> Outro |
| Integrated Audio Assets | Success | Added sign-in, message, call ring, and call answer sounds |
| Refactored Connection Manager | Success | Decoupled signaling to avoid circular imports |
| Fixed Server NameError | Success | Corrected ProfileUpdatePayload imports |
| Fixed Client AttributeError | Success | Fixed wx.BITMAP_TYPE_ANY typo |
| Migrated Echo Service to Bot | Success | Now a standalone bot using Bot SDK |
| Enhanced Audio/UX | Success | Added connecting loops, global hotkeys, and specific audio cues |
| Fixed Login KeyError | Success | Included username in server login response |
| Fixed wx.BITMAP_TYPE_ANY | Success | Corrected typo in login screen image loading |
| Optimized UI Performance | Success | Added debouncing to typing indicator and refined asyncio tasks |
| Accessibility & Parity | Success | Added names to all controls, menu bar, and shortcuts (Alt+1, Alt+2, etc.) |
| ListBox Optimization | Success | Throttled updates with Freeze/Thaw and batch-loading messages |
| Unified Search UI | Success | Integrated global search results into the main sidebar list |
| Directory Reorganization | Success | Moved bots and uploads into server/ directory |
| Expanded Registration | Success | Added email, first/last name to DB and all client forms |
| WebRTC Support | Success | Added WebRTC signaling and media logic to the Web Client |
| Fix Bot Imports | Success | Updated absolute imports for Bots and SDK after move |
| Default Contact Logic | Success | echo_service added to all new users upon registration |
| User Search API | Success | Added server search endpoint and client API integration |
| UI Layout Refinement | Success | Chat area hidden by default, added integrated Search bar |
| Planned runtime/config repair | Success | Before coding: identified SECRET_KEY import failure and missing runtime dependencies |
| Implemented runtime/config repair | Success | Added development SECRET_KEY fallback, .env.example, python-multipart dependency, and README setup step |
| Planned authenticated WebSocket CLI repair | Success | Before coding: identified stale headless client /ws/{user_id} flow |
| Implemented authenticated WebSocket CLI repair | Success | Updated scripts/headless_client.py to login, request /ws/ticket, and resolve target users |
| Planned conversation and offline messaging repair | Success | Before coding: identified spoofable sender_id, asymmetric history, and no offline replay |
| Implemented conversation and offline messaging repair | Success | Added conversations, participants, message recipient/delivery fields, trusted sender routing, typing forwarding, and offline replay |
| Planned echo routing repair | Success | Before coding: identified username/id mismatch for echo_service chat routing |
| Implemented echo routing repair | Success | Removed hardcoded echo chat loopback and route echo_service through the normal bot user id path |
| Planned server test isolation repair | Success | Before coding: rerun exposed hardcoded testuser3 collision in the persistent dev database |
| Implemented server test isolation repair | Success | Updated tests/test_server.py to register unique test users and emails |
| Verified repaired runtime and tests | Success | server.main imports, run_server.py starts, py_compile passes, and pytest passes with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 |
| Planned client service refactor | Success | Before coding: identified wx main window owning protocol envelopes, call media lifecycle, and notifications |
| Implemented client session service | Success | Added ClientSessionService to translate WebSocket envelopes into domain events and own outgoing protocol intents |
| Implemented client call service | Success | Added CallService to own active call peer/session state, media start/stop, accept/reject/hangup routing |
| Implemented client data and auth services | Success | Routed main window, profile dialog, and login screen through service wrappers instead of direct API calls |
| Implemented desktop notification service | Success | Added minimized/inactive chat and incoming call notifications with attention requests and optional sounds |
| Verified client refactor | Success | Added client service tests, py_compile passed, imports passed, and pytest passed with 11 tests |
| Planned main window modularization | Success | Before coding: identified contact, message, and call page construction still embedded inside MainWindow |
| Implemented main window modularization | Success | Moved contact, message, and call page builders into client/ui/main_window_views.py and reduced MainWindow size |
| Implemented contact click chat open | Success | Selecting a contact in the list now opens the IM view directly instead of only updating status text |
| Implemented global chat escape | Success | Added frame-level Escape handling so Esc leaves the chat view regardless of focused child control |
| Verified main window modularization | Success | py_compile passed, UI direct protocol/network grep is clean, and pytest passed with 11 tests |
| Planned main window controller split | Success | Before coding: identified contact, message, and call behavior methods still concentrated in MainWindow |
| Implemented contact controller split | Success | Moved contact list rendering, selection, search, and contact context-menu behavior into ContactsController |
| Implemented message controller split | Success | Moved message loading, rendering, send/file/typing/emoji/context-menu behavior into MessagesController |
| Implemented call controller split | Success | Moved call start, timeout, mute, hangup, stop, and answer behavior into CallsController |
| Verified main window controller split | Success | MainWindow reduced to about 411 lines; py_compile, client imports, and pytest all passed |
| Fixed contact list accidental navigation | Success | Single selection now only selects a contact; chat opens only on double-click or Enter |
| Fixed contact list Enter activation | Success | Added robust frame-level Return/Numpad Enter handling for focused contact list selection |
