"""Main chat window — accessibility-first redesign.

Three full-window views switched via wx.Simplebook:
  VIEW_CONTACTS (0): Contact/Recents list  (default)
  VIEW_MESSAGES (1): Conversation          (hidden until Send IM)
  VIEW_CALL     (2): Active call controls  (hidden until in a call)

Keyboard contract
─────────────────
Alt+1          → Contacts view
Alt+2          → Recents view
Enter on item  → Audio call
Shift+F10/App  → Context menu
Esc (messages) → Back to contacts
Ctrl+1…0       → Read last 10 messages aloud (requires accessible_output2)
"""

import os
import datetime
from urllib.parse import urlparse
import wx
import wx.adv
import structlog
from concurrent.futures import ThreadPoolExecutor

from ..network.api_client import APIClient
from ..network.ws_client   import WSClient
from shared.models import SettingsPayload, UserStatus
from ..services.calls import CallService
from ..services.data import ClientDataService
from ..services.notifications import DesktopNotificationService
from ..services.session import (
    ClientSessionService,
    ChatReceived,
    TypingChanged,
    PresenceChanged,
    ContactRequestReceived,
    IncomingCall,
    CallConnecting,
    CallAccepted,
    CallRejected,
    CallHungUp,
    SessionDisconnected,
    MessageRead,
)
from .settings            import SettingsDialog
from .find_people         import FindPeopleDialog
from .profile_dialog      import ProfileDialog
from .incoming_call_dialog import IncomingCallDialog
from .tray_icon import MainTrayIcon
from .views import build_contact_view, build_message_view, build_call_view
from .controllers.contacts import ContactsController
from .controllers.messages import MessagesController
from .controllers.calls    import CallsController
from ..audio.sounds import SoundPlayer
from ..services.settings_store import load_settings, save_settings, _SETTINGS_FILE

logger = structlog.get_logger()


def _resolve_udp_endpoint(api_base_url: str) -> tuple[str, int]:
    host = os.environ.get("SKYPE_UDP_HOST", "").strip()
    if not host:
        parsed = urlparse(
            api_base_url if "://" in api_base_url else f"http://{api_base_url}"
        )
        host = parsed.hostname or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    try:
        port = int(os.environ.get("SKYPE_UDP_PORT", "9000").strip())
    except ValueError:
        port = 9000
    return host, port


class MainWindow(wx.Frame):
    VIEW_CONTACTS = 0
    VIEW_MESSAGES = 1
    VIEW_CALL     = 2

    # ── Init ──────────────────────────────────────────────────────────

    def __init__(self, api_client: APIClient, ws_client: WSClient, user_data: dict):
        super().__init__(
            None,
            title=f"Skype™ Reborn — {user_data.get('username', 'User')}",
            size=(850, 660),
            name="Skype Main Window",
        )
        self.data_service = ClientDataService(api_client)
        self.ws_client  = ws_client
        self.user_data  = user_data
        self.settings   = load_settings()

        self.contacts:        list      = []
        self.search_results:  list      = []
        self.is_searching:    bool      = False
        self.selected_contact:dict|None = None
        self.current_conversation_id: str|None = None

        from ..audio.engine    import AudioEngine
        from ..network.udp_client import UDPClient
        self.session_service = ClientSessionService(ws_client, user_data["user_id"])
        self.audio_engine = AudioEngine()
        udp_host, udp_port = _resolve_udp_endpoint(api_client.base_url)
        logger.info("Voice UDP endpoint", host=udp_host, port=udp_port)
        self.udp_client = UDPClient(udp_host, udp_port)
        self.call_service = CallService(
            self.session_service,
            self.audio_engine,
            self.udp_client,
            user_data["user_id"],
        )
        self.notifications   = DesktopNotificationService(self)
        self._sound_player   = SoundPlayer()
        self.is_calling      = False
        self._call_minimized = False
        self._reply_to_entry      = None
        self._unread_counts: dict = {}        # peer_id → unread count
        self._last_message_times: dict = {}   # peer_id → datetime of last message
        self._call_start_time: datetime.datetime | None = None
        self._call_peer_id: str | None = None
        self._call_peer_name: str = "Contact"
        self._call_is_incoming: bool = False
        self._mute_on_answer: bool = False
        self._pending_call_records: dict = {}
        self._force_exit = False
        self._is_shutting_down = False
        self._tray_icon: MainTrayIcon | None = None
        self._tray_hint_shown = False

        self._pool        = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api")
        self._load_seq    = 0
        self._search_seq  = 0
        self._is_typing   = False
        self._typing_timer: wx.CallLater|None = None
        self._alive       = True

        # Structured message store for context menu / Ctrl+N reading
        self._message_items: list[dict] = []
        self._contact_mode = "contacts"     # "contacts" | "recents"
        self._current_view = self.VIEW_CONTACTS

        self.session_service.bind_websocket()
        self._bind_session_events()
        self.messages_controller = MessagesController(self)
        self.contacts_controller = ContactsController(self)
        self.calls_controller = CallsController(self)

        self._build_ui()
        self._ensure_tray_icon()
        self.CreateMenus()
        self.CreateStatusBar()
        self.SetStatusText("Ready")
        self.Centre()
        self.SetupShortcuts()
        self._pool.submit(self._bg_load_contacts)
        # Announce ONLINE so contacts see us as online immediately
        wx.CallAfter(self.session_service.send_presence, UserStatus.ONLINE)

    def _bind_session_events(self):
        self.session_service.on(ChatReceived, self._on_chat_received)
        self.session_service.on(TypingChanged, self._on_typing_changed)
        self.session_service.on(PresenceChanged, self._on_presence_changed)
        self.session_service.on(ContactRequestReceived, self._on_contact_request)
        self.session_service.on(IncomingCall, self._on_incoming_call)
        self.session_service.on(CallConnecting, self._on_call_connecting)
        self.session_service.on(CallAccepted, self._on_call_accepted)
        self.session_service.on(CallRejected, self._on_call_rejected)
        self.session_service.on(CallHungUp, self._on_call_hung_up)
        self.session_service.on(SessionDisconnected, self._on_session_disconnected)
        self.session_service.on(MessageRead, self._on_message_read)

    # ── Shortcuts ─────────────────────────────────────────────────────

    def SetupShortcuts(self):
        ID_ANSWER  = wx.NewIdRef()
        ID_HANGUP  = wx.NewIdRef()
        ID_RECENTS = wx.NewIdRef()
        ID_CONTACTS= wx.NewIdRef()
        ID_BACK    = wx.NewIdRef()
        # Ctrl+1…0 → read last 10 messages
        self._read_ids = [wx.NewIdRef() for _ in range(10)]

        self.Bind(wx.EVT_MENU, lambda e: self._answer_if_ringing(),                       id=ID_ANSWER)
        self.Bind(wx.EVT_MENU, lambda e: self.calls_controller.hang_up() if self.is_calling else None, id=ID_HANGUP)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_contact_mode("recents"),            id=ID_RECENTS)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_contact_mode("contacts"),           id=ID_CONTACTS)
        self.Bind(wx.EVT_MENU, lambda e: self._back_from_chat(),                          id=ID_BACK)
        for i, rid in enumerate(self._read_ids):
            self.Bind(wx.EVT_MENU, lambda e, idx=i: self.messages_controller.read_message(idx), id=rid)

        accel = [
            (wx.ACCEL_ALT,  wx.WXK_PAGEUP,   ID_ANSWER),
            (wx.ACCEL_ALT,  wx.WXK_PAGEDOWN, ID_HANGUP),
            (wx.ACCEL_ALT,  ord('1'),         ID_CONTACTS),
            (wx.ACCEL_ALT,  ord('2'),         ID_RECENTS),
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE,  ID_BACK),
            (wx.ACCEL_CTRL, ord(','),         wx.ID_PREFERENCES),
        ]
        for i, rid in enumerate(self._read_ids):
            key = ord('0') if i == 9 else ord(str(i + 1))
            accel.append((wx.ACCEL_CTRL, key, rid))
        self.SetAcceleratorTable(wx.AcceleratorTable(accel))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_global_char_hook)

    def _answer_if_ringing(self):
        if hasattr(self, "_incoming_call"):
            self.calls_controller.answer_call(self._incoming_call)

    def _on_global_char_hook(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE and self._current_view == self.VIEW_MESSAGES:
            self._back_from_chat()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self._current_view == self.VIEW_CONTACTS:
            focused = wx.Window.FindFocus()
            if focused is self.contact_list or self.contact_list.HasFocus():
                if self.contacts_controller.open_selected_contact():
                    return
        event.Skip()

    def _back_from_chat(self):
        if self._current_view == self.VIEW_MESSAGES:
            self._show_view(self.VIEW_CONTACTS)

    # ── Menus ─────────────────────────────────────────────────────────

    def CreateMenus(self):
        bar = wx.MenuBar()

        skype = wx.Menu()
        profile_item = skype.Append(wx.ID_ANY, "&My Profile…")
        skype.AppendSeparator()

        status_menu = wx.Menu()
        for s in ("ONLINE", "AWAY", "BUSY", "INVISIBLE"):
            item = status_menu.Append(wx.ID_ANY, s.capitalize())
            self.Bind(wx.EVT_MENU, lambda e, st=s: self._send_presence(st), item)
        skype.AppendSubMenu(status_menu, "&Change Status")

        skype.AppendSeparator()
        skype.Append(wx.ID_PREFERENCES, "S&ettings…\tCtrl+,")
        skype.AppendSeparator()
        skype.Append(wx.ID_EXIT, "Sign &Out")

        view = wx.Menu()
        cont_item = view.Append(wx.ID_ANY, "&Contacts\tAlt+1")
        rec_item  = view.Append(wx.ID_ANY, "&Recent Conversations\tAlt+2")

        help_ = wx.Menu()
        help_.Append(wx.ID_HELP,  "&Help Topics")
        help_.Append(wx.ID_ABOUT, "&About Skype Reborn")

        bar.Append(skype, "&Skype")
        bar.Append(view,  "&View")
        bar.Append(help_, "&Help")
        self.SetMenuBar(bar)

        self.Bind(wx.EVT_MENU, self.exit_application,                           id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self.OnSettings,                                 id=wx.ID_PREFERENCES)
        self.Bind(wx.EVT_MENU, self.OnViewProfile,                              profile_item)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_contact_mode("recents"),  rec_item)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_contact_mode("contacts"), cont_item)

    # ═══════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.panel = wx.Panel(self, name="Main Panel")
        root = wx.BoxSizer(wx.VERTICAL)

        self._book = wx.Simplebook(self.panel)
        self._book.AddPage(build_contact_view(self, self._book), "Contacts")
        self._book.AddPage(build_message_view(self, self._book), "Messages")
        self._book.AddPage(build_call_view(self, self._book), "Call")

        root.Add(self._book, 1, wx.EXPAND)
        self.panel.SetSizer(root)

        # Timers
        self._call_timer     = wx.Timer(self)
        self._presence_timer = wx.Timer(self)
        self._ring_timer     = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.calls_controller.on_timeout,                  self._call_timer)
        self.Bind(wx.EVT_TIMER, lambda e: self.contacts_controller.update_list(),  self._presence_timer)
        self.Bind(wx.EVT_TIMER, self._on_ring_timer,                               self._ring_timer)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_MENU,  self.OnSettings, id=wx.ID_PREFERENCES)

    # ═══════════════════════════════════════════════════════════════════
    # VIEW SWITCHING
    # ═══════════════════════════════════════════════════════════════════

    def _show_view(self, view: int):
        self._current_view = view
        self._book.SetSelection(view)
        if view == self.VIEW_CONTACTS:
            wx.CallAfter(self.contact_list.SetFocus)
        elif view == self.VIEW_MESSAGES:
            wx.CallAfter(self.message_input.SetFocus)

    def _switch_contact_mode(self, mode: str):
        self._contact_mode = mode
        if self._current_view != self.VIEW_CONTACTS:
            self._show_view(self.VIEW_CONTACTS)
        if self.is_searching:
            self.search_ctrl.Clear(); self.is_searching = False
        self.contacts_controller.update_list()
        wx.CallAfter(self.contact_list.SetFocus)
        # Announce the active tab so the switch is not silent
        label = "Recent Conversations" if mode == "recents" else "Contacts"
        self.SetStatusText(label)
        try:
            from accessible_output2.outputs.auto import Auto as _AO2
            _AO2().speak(label, interrupt=True)
        except Exception:
            pass

    def _on_minimize_call(self, event):
        self._call_minimized = True
        self._show_view(self.VIEW_CONTACTS)

    # ═══════════════════════════════════════════════════════════════════
    # CLOSE
    # ═══════════════════════════════════════════════════════════════════

    def OnClose(self, event):
        if self._is_shutting_down:
            if event:
                event.Skip()
            return
        if self._force_exit or (event is not None and not event.CanVeto()):
            self._shutdown_and_destroy()
            if event:
                event.Skip()
            return
        self._minimize_to_tray()
        if event and event.CanVeto():
            event.Veto()

    def _shutdown_and_destroy(self):
        self._is_shutting_down = True
        self._alive = False
        self._call_timer.Stop()
        self._presence_timer.Stop()
        self._ring_timer.Stop()
        if self._typing_timer:
            self._typing_timer.Stop()
        self.call_service.end_local()
        self.ws_client.close()
        self.data_service.close()
        self._pool.shutdown(wait=False)
        if self._tray_icon:
            try:
                self._tray_icon.RemoveIcon()
            except Exception:
                pass
            try:
                self._tray_icon.Destroy()
            except Exception:
                pass
            self._tray_icon = None
        # Play sign-out sound synchronously so it finishes before the process exits
        self._play_exit_sound()
        self.Destroy()

    def _ensure_tray_icon(self):
        if self._tray_icon is None:
            try:
                self._tray_icon = MainTrayIcon(self)
            except Exception as exc:
                logger.warning("Could not initialize tray icon", error=str(exc))
                self._tray_icon = None

    def _minimize_to_tray(self):
        self._ensure_tray_icon()
        if self._tray_icon is None:
            self.Iconize(True)
            return
        self.Hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            try:
                note = wx.adv.NotificationMessage(
                    title="Skype Reborn",
                    message="Still running in the tray. Double-click the tray icon to reopen.",
                    parent=self,
                )
                note.Show(timeout=4)
            except Exception:
                pass

    def restore_from_tray(self):
        self.Show()
        if self.IsIconized():
            self.Iconize(False)
        self.Raise()
        try:
            self.RequestUserAttention(wx.USER_ATTENTION_INFO)
        except Exception:
            pass

    def exit_application(self, event=None):
        self._force_exit = True
        self.Close()

    def _play_exit_sound(self):
        path = os.path.join("assets", "sounds", "misk_signout.wav")
        if not os.path.exists(path):
            return
        try:
            import sounddevice as sd
            from ..audio.sounds import read_wav_float
            data, fs = read_wav_float(path)
            sd.play(data, fs)
            sd.wait()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # CONTACTS
    # ═══════════════════════════════════════════════════════════════════

    def _bg_load_contacts(self):
        contacts = self.data_service.get_contacts()
        wx.CallAfter(self._on_contacts_loaded, contacts)

    def _on_contacts_loaded(self, contacts):
        if not self._alive: return
        self.contacts = contacts
        if not self.is_searching:
            self.contacts_controller.update_list()

    def TriggerUpdate(self):
        self._presence_timer.StartOnce(500)

    # ═══════════════════════════════════════════════════════════════════
    # STATUS / PROFILE
    # ═══════════════════════════════════════════════════════════════════

    def _send_presence(self, status_str: str):
        self.session_service.send_presence(UserStatus[status_str])

    def OnViewProfile(self, event):
        dlg = ProfileDialog(self, self.data_service, self.user_data)
        dlg.ShowModal(); dlg.Destroy()

    def OnFindPeople(self, event):
        def do_search(query):
            self.SetStatusText(f"Searching for '{query}'…")
            return self.data_service.search_users(query)
        def do_add(user):
            self.data_service.add_contact(user["username"])
            self.SetStatusText(f"Added {user['display_name']} to contacts")
            self._pool.submit(self._bg_load_contacts)
        dlg = FindPeopleDialog(self, do_search, do_add)
        dlg.ShowModal(); dlg.Destroy()

    def _update_title(self):
        """Reflect total unread count in the window title bar."""
        total    = sum(self._unread_counts.values())
        username = self.user_data.get("username", "User")
        base     = f"Skype™ Reborn — {username}"
        self.SetTitle(f"({total}) {base}" if total else base)

    def OnSettings(self, event):
        def on_save(new_settings):
            self.settings = new_settings
            save_settings(new_settings)
            self.SetStatusText(f"Settings saved to {_SETTINGS_FILE}")
        dlg = SettingsDialog(self, self.settings, on_save)
        dlg.ShowModal(); dlg.Destroy()

    # ═══════════════════════════════════════════════════════════════════
    # SOUNDS
    # ═══════════════════════════════════════════════════════════════════

    def play_sound(self, filename: str, loop: bool = False):
        path = os.path.join("assets", "sounds", filename)
        self._sound_player.play(path, loop)

    def stop_looping_sound(self):
        self._sound_player.stop()
        self._ring_timer.Stop()

    def _on_ring_timer(self, event):
        self.play_sound("call_connecting.wav")

    # ═══════════════════════════════════════════════════════════════════
    # SESSION EVENTS
    # ═══════════════════════════════════════════════════════════════════

    def _contact_name(self, user_id: str, fallback: str = "Contact") -> str:
        return next(
            (c["display_name"] for c in self.contacts if c["id"] == user_id),
            fallback,
        )

    def _on_chat_received(self, event: ChatReceived):
        if not self._alive: return
        sender_name = self._contact_name(event.sender_id)
        self._last_message_times[event.sender_id] = datetime.datetime.now()

        is_open_conversation = (
            self._current_view == self.VIEW_MESSAGES
            and self.current_conversation_id == event.sender_id
        )

        # Reaction messages are handled separately — they annotate an existing item
        if event.content.startswith("[react:") and event.content.endswith("]"):
            emoji = event.content[7:-1]
            if is_open_conversation:
                self.messages_controller.apply_incoming_reaction(emoji, sender_name)
            self.play_sound("msg_react.wav")
            if not is_open_conversation or self.IsIconized() or not self.IsActive():
                self.notifications.notify_reaction(sender_name, emoji)
            return

        entry = {
            "sender": sender_name, "content": event.content,
            "dt": datetime.datetime.now(), "is_mine": False, "msg_id": "",
            "delivered": False, "read": False,
        }
        if is_open_conversation:
            self.messages_controller.append_item(entry, scroll=False)
            self.session_service.send_read_receipt(event.sender_id)
        else:
            self._unread_counts[event.sender_id] = (
                self._unread_counts.get(event.sender_id, 0) + 1
            )
            self._update_title()
            self.contacts_controller.update_list()
        self.play_sound("im_getmessage.wav")
        should_notify = (
            not is_open_conversation
            or self.IsIconized()
            or not self.IsActive()
        )
        if should_notify:
            self.notifications.notify_chat_message(sender_name, event.content)

    def _on_typing_changed(self, event: TypingChanged):
        if not self._alive: return
        if (
            self._current_view == self.VIEW_MESSAGES
            and self.selected_contact
            and self.current_conversation_id == event.user_id
        ):
            label = "Typing…" if event.is_typing else ""
            self.msg_header.SetLabel(
                f"Conversation with {self.selected_contact['display_name']}"
                + (f"  —  {label}" if label else "")
            )

    def _on_contact_request(self, event: ContactRequestReceived):
        if not self._alive: return
        self.play_sound("misk_chatrequest.wav")
        self._pool.submit(self._bg_load_contacts)

    def _on_presence_changed(self, event: PresenceChanged):
        if not self._alive: return
        new_status = event.status.value
        for c in self.contacts:
            if c["id"] == event.user_id:
                old_status = c.get("status", "OFFLINE")
                c["status"] = new_status
                if old_status != new_status:
                    name = c.get("display_name", "Contact")
                    if new_status == "ONLINE" and old_status in ("OFFLINE", "INVISIBLE"):
                        self.notifications.notify_presence_change(name, True)
                    elif new_status in ("OFFLINE", "INVISIBLE") and old_status == "ONLINE":
                        self.notifications.notify_presence_change(name, False)
                self.TriggerUpdate()
                return
        self._pool.submit(self._bg_load_contacts)

    def _on_incoming_call(self, event: IncomingCall):
        if not self._alive: return
        pl = event.payload
        self._incoming_call = pl
        snd = "call_ring_active.wav" if self.is_calling else "call_ring1.wav"
        self.play_sound(snd, loop=True)
        sender_name = self._contact_name(pl.sender_id, "Someone")
        self.notifications.notify_incoming_call(sender_name)
        dlg = IncomingCallDialog(self, sender_name)
        res = dlg.ShowModal()
        self._mute_on_answer = dlg.mute_on_answer
        dlg.Destroy()
        if res == wx.ID_YES:
            self.calls_controller.answer_call(pl)
        elif res == wx.ID_NO:
            self.call_service.reject(pl)
            self.stop_looping_sound()
        # wx.ID_CLOSE = minimize: keep ringing, user can answer via Alt+PageUp

    def _on_call_connecting(self, event: CallConnecting):
        if not self._alive: return
        if not self.call_service.is_active_session(event.payload):
            return
        self.call_status_text.SetLabel("Ringing…")

    def _on_call_accepted(self, event: CallAccepted):
        if not self._alive: return
        if not self.call_service.is_active_session(event.payload):
            return
        self._call_timer.Stop()
        self._ring_timer.Stop()
        self.stop_looping_sound()
        self.call_status_text.SetLabel("In call")
        self._call_start_time = datetime.datetime.now()
        self.call_service.remote_accepted()

    def _on_call_rejected(self, event: CallRejected):
        if not self._alive: return
        if not self.call_service.is_active_session(event.payload):
            return
        self._call_timer.Stop()
        self.call_status_text.SetLabel("Call rejected.")
        self.calls_controller.stop_call()

    def _on_call_hung_up(self, event: CallHungUp):
        if not self._alive: return
        if not self.call_service.is_active_session(event.payload):
            return
        self.call_status_text.SetLabel("Call ended.")
        self.calls_controller.stop_call()

    def _on_message_read(self, event: MessageRead):
        if not self._alive: return
        # The ACK is always about messages sent by us (peer_id == our user_id).
        # reader_id is the contact; update the open conversation if it matches.
        if (self._current_view == self.VIEW_MESSAGES
                and self.current_conversation_id == event.reader_id):
            if event.status == "read":
                self.messages_controller.mark_conversation_read()
            elif event.status == "delivered":
                self.messages_controller.mark_conversation_delivered()

    def _on_session_disconnected(self, event: SessionDisconnected):
        if not self._alive: return
        logger.warning("WebSocket disconnected")
        self.SetStatusText("Disconnected from server")

    # ═══════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════

    def _not_supported(self, feature: str):
        wx.MessageBox(
            f"{feature} are not yet supported in this version.",
            "Coming Soon", wx.OK | wx.ICON_INFORMATION, self,
        )
