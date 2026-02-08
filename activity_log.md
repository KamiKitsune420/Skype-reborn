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
