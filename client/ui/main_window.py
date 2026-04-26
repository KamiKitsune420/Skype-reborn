"""Main chat window.

Architecture: pure wx on the main thread.  All network I/O runs in a
ThreadPoolExecutor (API calls) or the WSClient daemon thread (WebSocket).
Results are pushed back to the main thread exclusively via wx.CallAfter,
so there is zero asyncio/await anywhere in this file.

Navigation is instant: OnContactSelected updates the header and shows a
"Loading…" placeholder synchronously in the event handler, then fires a
background task to fetch messages.  A monotonically-increasing _load_seq
counter lets the callback discard results that arrived after the user
already moved to a different contact.
"""

import wx
import wx.adv
import os
import threading
import structlog
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from ..network.api_client import APIClient
from ..network.ws_client import WSClient
from shared.models import (
    Envelope, MessageType,
    ChatMessagePayload, CallSignalPayload,
    ChatTypingPayload, PresenceUpdatePayload,
    SettingsPayload,
)
from .settings import SettingsFrame
from .find_people import FindPeopleDialog

logger = structlog.get_logger()


class MainWindow(wx.Frame):
    def __init__(self, api_client: APIClient, ws_client: WSClient, user_data: dict):
        super().__init__(
            None,
            title=f"Skype™ Reborn — {user_data.get('username', 'User')}",
            size=(1000, 700),
            name="Skype Main Window",
        )
        self.api_client = api_client
        self.ws_client = ws_client
        self.user_data = user_data
        self.settings = SettingsPayload() # Default settings

        self.contacts: list = []
        self.search_results: list = []
        self.is_searching = False
        self.selected_contact: dict | None = None
        self.current_conversation_id: str | None = None

        from ..audio.engine import AudioEngine
        from ..network.udp_client import UDPClient
        self.audio_engine = AudioEngine()
        self.udp_client = UDPClient("127.0.0.1", 9000)
        self.is_calling = False
        self.active_session_id: UUID | None = None
        self.looping_sound = None

        # Thread pool for API calls (contacts, messages, search, upload)
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api")

        # Monotonic counters — background tasks check these to discard stale results
        self._load_seq = 0
        self._search_seq = 0

        # Typing indicator state
        self._is_typing = False
        self._typing_timer: wx.CallLater | None = None

        # Window-alive guard: prevents wx.CallAfter callbacks from touching
        # UI controls after the window has been destroyed
        self._alive = True

        # Register WS callbacks before connect() is called in app.py
        self.ws_client.on_message_callback = self.on_ws_message
        self.ws_client.on_disconnect_callback = self.on_ws_disconnect

        self._build_ui()
        self.CreateMenus()
        self.CreateStatusBar()
        self.SetStatusText("Ready")
        self.Centre()
        self.SetupShortcuts()

        # Load contacts immediately in background
        self._pool.submit(self._bg_load_contacts)

    # ── Shortcuts ────────────────────────────────────────────────────

    def SetupShortcuts(self):
        ID_ANSWER = wx.NewIdRef()
        ID_HANGUP = wx.NewIdRef()
        ID_SEARCH = wx.NewIdRef()
        ID_RECENTS = wx.NewIdRef()
        ID_CONTACTS = wx.NewIdRef()

        self.Bind(wx.EVT_MENU, lambda e: self._answer_if_ringing(), id=ID_ANSWER)
        self.Bind(wx.EVT_MENU, lambda e: self.HangUp() if self.is_calling else None, id=ID_HANGUP)
        self.Bind(wx.EVT_MENU, lambda e: self.OnRecentsFocus(e), id=ID_RECENTS)
        self.Bind(wx.EVT_MENU, lambda e: self.OnContactsFocus(e), id=ID_CONTACTS)

        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_ALT, wx.WXK_PAGEUP,              ID_ANSWER),
            (wx.ACCEL_ALT, wx.WXK_PAGEDOWN,            ID_HANGUP),
            (wx.ACCEL_ALT, ord('1'),                   ID_RECENTS),
            (wx.ACCEL_ALT, ord('2'),                   ID_CONTACTS),
            (wx.ACCEL_CTRL, ord(','),                  wx.ID_PREFERENCES),
        ]))

    def _answer_if_ringing(self):
        if hasattr(self, '_incoming_call'):
            self.AnswerCall(self._incoming_call)

    # ── Menus ────────────────────────────────────────────────────────

    def CreateMenus(self):
        bar = wx.MenuBar()

        # Skype Menu
        skype = wx.Menu()
        skype.Append(wx.ID_ANY, "New &Conversation…\tCtrl+N")
        skype.AppendSeparator()
        
        # Status Submenu
        status_menu = wx.Menu()
        for s in ("ONLINE", "AWAY", "BUSY", "INVISIBLE"):
            item = status_menu.Append(wx.ID_ANY, s.capitalize())
            # Capture status string properly in lambda
            self.Bind(wx.EVT_MENU, lambda e, st=s: self._send_presence(st), item)
        skype.AppendSubMenu(status_menu, "&Change Status")
        
        skype.Append(wx.ID_ANY, "Set &Mood Message…")
        skype.AppendSeparator()
        skype.Append(wx.ID_PREFERENCES, "S&ettings…\tCtrl+,")
        skype.AppendSeparator()
        skype.Append(wx.ID_EXIT, "Sign &Out")

        # View Menu
        view = wx.Menu()
        view.Append(wx.ID_ANY, "&Recent Conversations\tAlt+1")
        view.Append(wx.ID_ANY, "&Contacts\tAlt+2")
        view.AppendSeparator()
        view.Append(wx.ID_ANY, "&Profile")

        # Help Menu
        help_ = wx.Menu()
        help_.Append(wx.ID_HELP, "&Help Topics\tCtrl+H")
        help_.Append(wx.ID_ABOUT, "&About Skype Reborn")

        bar.Append(skype, "&Skype")
        bar.Append(view,  "&View")
        bar.Append(help_, "&Help")

        self.SetMenuBar(bar)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)

    # ── Layout ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.panel = wx.Panel(self, name="Main Panel")
        root = wx.BoxSizer(wx.HORIZONTAL)

        # ── Sidebar ──────────────────────────────────────────────────
        sidebar = wx.Panel(self.panel, size=(300, -1), style=wx.BORDER_NONE,
                           name="Sidebar Panel")
        sidebar.SetBackgroundColour(wx.Colour(245, 245, 245))
        sb = wx.BoxSizer(wx.VERTICAL)

        # Profile bar
        prof = wx.Panel(sidebar, name="Profile Panel")
        prof.SetBackgroundColour(wx.Colour(0, 114, 198))
        prof_row = wx.BoxSizer(wx.HORIZONTAL)

        avatar = os.path.join("assets", "images", "profile_anonymous.png")
        if os.path.exists(avatar):
            img = wx.Image(avatar, wx.BITMAP_TYPE_ANY).Scale(40, 40, wx.IMAGE_QUALITY_HIGH)
            prof_row.Add(wx.StaticBitmap(prof, -1, wx.Bitmap(img), name="My Avatar"),
                         0, wx.ALL, 8)

        self.profile_name = wx.StaticText(
            prof, label=self.user_data.get("username", "User"), name="My Profile Name"
        )
        f = self.profile_name.GetFont()
        f.SetPointSize(10)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.profile_name.SetFont(f)
        self.profile_name.SetForegroundColour(wx.WHITE)

        self.status_btn = wx.Button(prof, label="▼", size=(22, 22),
                                     style=wx.BU_EXACTFIT, name="Status and Mood Menu")
        self.status_btn.SetToolTip("Change your online status or mood")

        prof_row.Add(self.profile_name, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        prof_row.Add(self.status_btn,   0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        prof.SetSizer(prof_row)
        sb.Add(prof, 0, wx.EXPAND)

        # Actions Row (View Profile, Find People)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.profile_btn = wx.Button(sidebar, label="&View Profile", name="View My Profile")
        self.find_btn = wx.Button(sidebar, label="&Find People", name="Search for People")
        actions.Add(self.profile_btn, 1, wx.EXPAND | wx.ALL, 5)
        actions.Add(self.find_btn, 1, wx.EXPAND | wx.ALL, 5)
        sb.Add(actions, 0, wx.EXPAND)

        self.list_label = wx.StaticText(sidebar, label="CONTACTS", name="List Content Header")
        self.list_label.SetForegroundColour(wx.Colour(100, 100, 100))
        lf = self.list_label.GetFont()
        lf.SetPointSize(8)
        self.list_label.SetFont(lf)
        sb.Add(self.list_label, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 8)

        self.contact_list = wx.ListBox(sidebar, style=wx.LB_SINGLE | wx.BORDER_NONE,
                                        name="Contact and Search List")
        self.contact_list.SetToolTip("Select a contact to start chatting")
        sb.Add(self.contact_list, 1, wx.EXPAND)

        sidebar.SetSizer(sb)
        root.Add(sidebar, 0, wx.EXPAND)

        # ── Chat area ────────────────────────────────────────────────
        self.chat_area = wx.Panel(self.panel, name="Conversation Panel")
        self.chat_area.SetBackgroundColour(wx.WHITE)
        ca = wx.BoxSizer(wx.VERTICAL)

        # Header
        self.header_panel = wx.Panel(self.chat_area, name="Conversation Header")
        self.header_panel.SetBackgroundColour(wx.Colour(250, 250, 250))
        hdr = wx.BoxSizer(wx.HORIZONTAL)
        hdr_font = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)

        self.chat_header = wx.StaticText(self.header_panel, label="Welcome to Skype™",
                                          name="Active Chat Contact Name")
        self.chat_header.SetFont(hdr_font)
        hdr.Add(self.chat_header, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 14)

        self.typing_status = wx.StaticText(self.header_panel, label="",
                                            name="Typing Notification")
        self.typing_status.SetForegroundColour(wx.Colour(128, 128, 128))
        hdr.Add(self.typing_status, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 14)

        self.header_panel.SetSizer(hdr)
        ca.Add(self.header_panel, 0, wx.EXPAND)

        # Message history — plain multiline, fastest rendering on Windows
        self.message_history = wx.TextCtrl(
            self.chat_area,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
            name="Chat Message History",
        )
        ca.Add(self.message_history, 1, wx.EXPAND | wx.ALL, 4)

        # Call panel
        self.call_panel = wx.Panel(self.chat_area, name="In-Call Status Panel")
        self.call_panel.SetBackgroundColour(wx.Colour(0, 175, 240))
        cp = wx.BoxSizer(wx.HORIZONTAL)
        self.call_status_text = wx.StaticText(self.call_panel, label="Calling…",
                                               style=wx.ALIGN_CENTER)
        self.call_status_text.SetForegroundColour(wx.WHITE)
        self.call_status_text.SetFont(hdr_font)
        cp.Add(self.call_status_text, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        self.call_panel.SetSizer(cp)
        ca.Add(self.call_panel, 0, wx.EXPAND)
        self.call_panel.Hide()

        # Input
        self.input_panel = wx.Panel(self.chat_area, name="Message Entry Area")
        inp = wx.BoxSizer(wx.HORIZONTAL)

        self.file_btn = wx.Button(self.input_panel, label="+", size=(30, 30),
                                   name="Send File Button")
        inp.Add(self.file_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        inp.Add(wx.StaticText(self.input_panel, label="&Message"),
                0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        self.message_input = wx.TextCtrl(
            self.input_panel,
            style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE,
            name="Message Input Box",
        )
        self.message_input.SetHint("Type a message here…")
        inp.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 8)

        btns = wx.BoxSizer(wx.VERTICAL)
        self.send_btn = wx.Button(self.input_panel, label="&Send", name="Send Message Button")
        self.call_btn = wx.Button(self.input_panel, label="&Call", name="Start Voice Call Button")
        btns.Add(self.send_btn, 0, wx.BOTTOM, 4)
        btns.Add(self.call_btn)
        inp.Add(btns, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.input_panel.SetSizer(inp)
        ca.Add(self.input_panel, 0, wx.EXPAND)

        self.chat_area.SetSizer(ca)
        root.Add(self.chat_area, 1, wx.EXPAND)

        self.chat_area.Hide()
        self.panel.SetSizer(root)

        # Timers
        self._call_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_call_timeout, self._call_timer)

        self._presence_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.UpdateContactList(), self._presence_timer)

        # Bindings
        self.send_btn.Bind(wx.EVT_BUTTON, self.OnSend)
        self.call_btn.Bind(wx.EVT_BUTTON, self.OnCall)
        self.file_btn.Bind(wx.EVT_BUTTON, self.OnSendFile)
        self.status_btn.Bind(wx.EVT_BUTTON, self.OnStatusMenu)
        self.profile_btn.Bind(wx.EVT_BUTTON, self.OnViewProfile)
        self.find_btn.Bind(wx.EVT_BUTTON, self.OnFindPeople)
        
        self.contact_list.Bind(wx.EVT_LISTBOX, self.OnContactSelected)
        self.contact_list.Bind(wx.EVT_LISTBOX_DCLICK, self.OnContactActivated)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_MENU, self.OnSettings, id=wx.ID_PREFERENCES)

    # ── Actions ──────────────────────────────────────────────────────

    def OnViewProfile(self, event):
        # Simplified: Show user data in a message box
        msg = f"Skype Name: {self.user_data['username']}\n"
        msg += f"Display Name: {self.user_data.get('display_name', 'Not set')}"
        wx.MessageBox(msg, "My Profile", wx.OK | wx.ICON_INFORMATION)
        self.SetStatusText("Viewing profile")

    def OnFindPeople(self, event):
        def do_search(query):
            self.SetStatusText(f"Searching for '{query}'...")
            return self.api_client.search_users(query)
            
        def do_add(user):
            self.api_client.add_contact(user["username"])
            self.SetStatusText(f"Added {user['display_name']} to contacts")
            self._pool.submit(self._bg_load_contacts)

        dlg = FindPeopleDialog(self, do_search, do_add)
        dlg.ShowModal()
        dlg.Destroy()

    def OnSettings(self, event):
        def save_settings(new_settings):
            self.settings = new_settings
            self.SetStatusText("Settings saved")
            # Apply settings (e.g. if we had theme switching logic)
            
        dlg = SettingsFrame(self, self.settings, save_settings)
        dlg.ShowModal()
        dlg.Destroy()

    # ── App close ────────────────────────────────────────────────────

    def OnClose(self, event):
        self._alive = False
        self._call_timer.Stop()
        self._presence_timer.Stop()
        if self._typing_timer:
            self._typing_timer.Stop()
        self._pool.shutdown(wait=False)
        self.audio_engine.stop()
        self.udp_client.stop()
        self.ws_client.close()
        self.api_client.close()
        self.Destroy()

    # ── Helpers ──────────────────────────────────────────────────────

    def _guard(self, fn):
        """Return a wx.CallAfter-safe wrapper that no-ops if the window is gone."""
        def wrapper(*args, **kwargs):
            if self._alive:
                fn(*args, **kwargs)
        return wrapper

    # ── Status ───────────────────────────────────────────────────────

    def OnStatusMenu(self, event):
        menu = wx.Menu()
        for s in ("ONLINE", "AWAY", "BUSY", "INVISIBLE"):
            item = menu.Append(wx.ID_ANY, s)
            self.Bind(wx.EVT_MENU, lambda e, st=s: self._send_presence(st), item)
        self.PopupMenu(menu)

    def _send_presence(self, status_str: str):
        from shared.models import UserStatus
        payload = PresenceUpdatePayload(
            user_id=self.user_data["user_id"],
            status=UserStatus[status_str],
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.PRESENCE_UPDATE, payload=payload.model_dump())
        )

    # ── Tab focus ────────────────────────────────────────────────────

    def OnRecentsFocus(self, event):
        self.is_searching = False
        self.list_label.SetLabel("RECENT CONVERSATIONS")
        self.UpdateContactList()
        self.contact_list.SetFocus()
        self.SetStatusText("Switched to Recent Conversations tab")

    def OnContactsFocus(self, event):
        self.is_searching = False
        self.list_label.SetLabel("CONTACTS")
        self.UpdateContactList()
        self.contact_list.SetFocus()
        self.SetStatusText("Switched to Contacts tab")

    # ── Sounds ───────────────────────────────────────────────────────

    def play_sound(self, filename: str, loop: bool = False):
        path = os.path.join("assets", "sounds", filename)
        if not os.path.exists(path):
            return None
        sound = wx.adv.Sound(path)
        if not sound.IsOk():
            return None
        flags = wx.adv.SOUND_ASYNC | (wx.adv.SOUND_LOOP if loop else 0)
        sound.Play(flags)
        if loop:
            self.looping_sound = sound
        return sound

    def stop_looping_sound(self):
        wx.adv.Sound.Stop()
        self.looping_sound = None

    # ── Contacts ─────────────────────────────────────────────────────

    def _bg_load_contacts(self):
        contacts = self.api_client.get_contacts()
        wx.CallAfter(self._on_contacts_loaded, contacts)

    def _on_contacts_loaded(self, contacts):
        if not self._alive:
            return
        self.contacts = contacts
        if not self.is_searching:
            self.UpdateContactList()

    def TriggerUpdate(self):
        """Debounce presence redraws — restart 500 ms timer on each call."""
        self._presence_timer.StartOnce(500)

    def UpdateContactList(self):
        if self.is_searching:
            self.list_label.SetLabel("SEARCH RESULTS")
            new_items = [u["display_name"] for u in self.search_results]
            if not new_items:
                new_items = ["No results found."]
        else:
            self.contacts.sort(key=lambda c: (c["status"] != "ONLINE", c["display_name"]))
            new_items = [
                f"{'●' if c['status'] == 'ONLINE' else '○'} {c['display_name']}"
                for c in self.contacts
            ]
            if not new_items:
                new_items = ["No contacts found."]

        if list(self.contact_list.GetStrings()) == new_items:
            return  # Nothing changed — skip the redraw

        selected_id = self.selected_contact["id"] if self.selected_contact else None

        self.contact_list.Freeze()
        self.contact_list.Set(new_items)
        if selected_id and not self.is_searching:
            for i, c in enumerate(self.contacts):
                if c["id"] == selected_id:
                    self.contact_list.SetSelection(i)
                    break
        self.contact_list.Thaw()

    # ── Search ───────────────────────────────────────────────────────

    def OnSearch(self, event):
        query = self.search_ctrl.GetValue().strip()
        if not query:
            self.is_searching = False
            self.UpdateContactList()
            return
        self.is_searching = True
        self._search_seq += 1
        seq = self._search_seq
        self._pool.submit(self._bg_search, query, seq)

    def _bg_search(self, query: str, seq: int):
        results = self.api_client.search_users(query)
        wx.CallAfter(self._on_search_done, query, seq, results)

    def _on_search_done(self, query: str, seq: int, results):
        if not self._alive or seq != self._search_seq:
            return
        self.search_results = results
        self.UpdateContactList()
        self.contact_list.SetFocus()

    def OnSearchText(self, event):
        if not self.search_ctrl.GetValue():
            self.is_searching = False
            self.UpdateContactList()

    # ── Contact selection — INSTANT ───────────────────────────────────

    def OnContactSelected(self, event):
        """Single-click / arrow-key navigation.  Instant UI update, async message load."""
        idx = self.contact_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return

        if self.is_searching:
            # Just preview the name in the header; activation happens on double-click
            if idx < len(self.search_results):
                self.chat_header.SetLabel(self.search_results[idx]["display_name"])
            return

        if idx >= len(self.contacts):
            return

        contact = self.contacts[idx]

        # ── Everything below is synchronous — zero delay ──────────────
        self.selected_contact = contact
        self.current_conversation_id = contact["id"]
        self.chat_header.SetLabel(contact["display_name"])
        self.message_history.SetValue("Loading…")

        if not self.chat_area.IsShown():
            self.chat_area.Show()
            self.panel.Layout()

        # Increment seq so any in-flight load for the previous contact is discarded
        self._load_seq += 1
        self._pool.submit(self._bg_load_messages, contact["id"], self._load_seq)

    def OnContactActivated(self, event):
        """Double-click on a search result → prompt to add contact."""
        if not self.is_searching:
            return
        idx = self.contact_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self.search_results):
            return
        user = self.search_results[idx]
        res = wx.MessageBox(
            f"Add {user['display_name']} to your contacts?", "Skype™ Reborn", wx.YES_NO
        )
        if res == wx.YES:
            self._pool.submit(self._bg_add_contact, user["username"])

    def _bg_add_contact(self, username: str):
        self.api_client.add_contact(username)
        contacts = self.api_client.get_contacts()
        wx.CallAfter(self._on_add_contact_done, contacts)

    def _on_add_contact_done(self, contacts):
        if not self._alive:
            return
        self.contacts = contacts
        self.is_searching = False
        self.search_ctrl.Clear()
        self.UpdateContactList()

    # ── Messages ─────────────────────────────────────────────────────

    def _bg_load_messages(self, conv_id: str, seq: int):
        messages = self.api_client.get_messages(conv_id)
        wx.CallAfter(self._on_messages_loaded, seq, messages)

    def _on_messages_loaded(self, seq: int, messages):
        if not self._alive or seq != self._load_seq:
            return  # Stale — user already moved to another contact
        if not messages:
            self.message_history.SetValue("")
            return
        my_id = self.user_data["user_id"]
        name = self.selected_contact["display_name"]
        text = "\n".join(
            f"{'Me' if m['sender_id'] == my_id else name}: {m['content']}"
            for m in messages
        )
        self.message_history.SetValue(text)
        self.message_history.SetInsertionPointEnd()

    def append_message(self, sender: str, content: str):
        if self.message_history.GetValue() == "Loading…":
            self.message_history.SetValue(f"{sender}: {content}\n")
        else:
            self.message_history.AppendText(f"{sender}: {content}\n")
        self.message_history.SetInsertionPointEnd()

    # ── Typing indicator ─────────────────────────────────────────────

    def OnTyping(self, event):
        if not self.current_conversation_id:
            return
        if not self._is_typing:
            self._is_typing = True
            self._send_typing(True)
        # Restart the idle countdown every keystroke
        if self._typing_timer and self._typing_timer.IsRunning():
            self._typing_timer.Restart(3000)
        else:
            self._typing_timer = wx.CallLater(3000, self._on_typing_idle)

    def _on_typing_idle(self):
        self._is_typing = False
        self._typing_timer = None
        self._send_typing(False)

    def _send_typing(self, is_typing: bool):
        if not self.current_conversation_id:
            return
        payload = ChatTypingPayload(
            conversation_id=self.current_conversation_id,
            user_id=self.user_data["user_id"],
            is_typing=is_typing,
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CHAT_TYPING, payload=payload.model_dump())
        )

    # ── Send message ─────────────────────────────────────────────────

    def OnSend(self, event):
        content = self.message_input.GetValue().strip()
        if not content or not self.current_conversation_id:
            return
        payload = ChatMessagePayload(
            conversation_id=self.current_conversation_id,
            sender_id=self.user_data["user_id"],
            content=content,
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump())
        )
        self.append_message("Me", content)
        self.message_input.Clear()
        self.play_sound("im_sendmessage.wav")

    # ── File transfer ────────────────────────────────────────────────

    def OnSendFile(self, event):
        if not self.current_conversation_id:
            return
        with wx.FileDialog(self, "Select file to send",
                           wildcard="All files (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            path = dlg.GetPath()

        filename = os.path.basename(path)
        conv_id = self.current_conversation_id
        self.append_message("System", f"Sending {filename}…")
        self._pool.submit(self._bg_upload, path, filename, conv_id)

    def _bg_upload(self, path: str, filename: str, conv_id: str):
        try:
            with open(path, "rb") as f:
                content = f.read()
            success, res = self.api_client.upload_file(conv_id, filename, content)
        except Exception as e:
            success, res = False, str(e)
        wx.CallAfter(self._on_upload_done, success, filename, res)

    def _on_upload_done(self, success: bool, filename: str, res):
        if not self._alive:
            return
        if success:
            self.append_message("Me", f"Sent file: {filename}")
        else:
            self.append_message("System", f"Failed to send {filename}: {res}")

    # ── Calls ────────────────────────────────────────────────────────

    def OnCall(self, event):
        if self.is_calling:
            self.HangUp()
            return
        if not self.selected_contact:
            return

        self.play_sound("call_request_sent.wav")
        self.is_calling = True
        self.call_btn.SetLabel("Hang Up")
        self.call_status_text.SetLabel(f"Calling {self.selected_contact['display_name']}…")
        self.call_panel.Show()
        self.chat_area.Layout()

        self.active_session_id = uuid4()
        payload = CallSignalPayload(
            session_id=str(self.active_session_id),
            target_id=self.selected_contact["id"],
            sender_id=self.user_data["user_id"],
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CALL_INITIATE, payload=payload.model_dump())
        )
        self.message_history.AppendText(f"Calling {self.selected_contact['display_name']}…\n")
        self.udp_client.start(
            self.active_session_id, self.audio_engine.receive_audio,
            user_id=self.user_data["user_id"],
        )
        self._call_timer.StartOnce(30_000)  # 30-second no-answer timeout

    def _on_call_timeout(self, event):
        if self.is_calling:
            self.message_history.AppendText("Call timed out — no answer.\n")
            self.HangUp()

    def HangUp(self):
        self._call_timer.Stop()
        if self.active_session_id and self.selected_contact:
            payload = CallSignalPayload(
                session_id=str(self.active_session_id),
                target_id=self.selected_contact["id"],
                sender_id=self.user_data["user_id"],
            )
            self.ws_client.send_envelope(
                Envelope(type=MessageType.CALL_HANGUP, payload=payload.model_dump())
            )
        self.stop_call()

    def stop_call(self):
        self._call_timer.Stop()
        self.stop_looping_sound()
        self.audio_engine.stop()
        self.udp_client.stop()
        self.is_calling = False
        self.call_btn.SetLabel("Call")
        self.call_panel.Hide()
        self.chat_area.Layout()
        self.message_history.AppendText("Call ended.\n")
        self.play_sound("call_end.wav")
        if hasattr(self, "_incoming_call"):
            del self._incoming_call

    def AnswerCall(self, payload):
        self._call_timer.Stop()
        self.stop_looping_sound()
        self.play_sound("Call_Answer.wav")
        self.active_session_id = UUID(payload.session_id)

        accept = CallSignalPayload(
            session_id=payload.session_id,
            target_id=payload.sender_id,
            sender_id=self.user_data["user_id"],
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CALL_ACCEPT, payload=accept.model_dump())
        )
        self.udp_client.start(
            self.active_session_id, self.audio_engine.receive_audio,
            user_id=self.user_data["user_id"],
        )
        self.audio_engine.start(self.udp_client.send_audio)
        self.is_calling = True

        if not self.chat_area.IsShown():
            self.chat_area.Show()
        self.call_status_text.SetLabel("In call")
        self.call_panel.Show()
        self.panel.Layout()
        self.call_btn.SetLabel("Hang Up")
        self.message_history.AppendText("Call started.\n")

    # ── WebSocket handler (always on main thread via wx.CallAfter) ────

    def on_ws_message(self, envelope: Envelope):
        if not self._alive:
            return
        t = envelope.type

        if t == MessageType.CHAT_RECEIVE:
            payload = ChatMessagePayload(**envelope.payload)
            sender = self.selected_contact["display_name"] if self.selected_contact else "Friend"
            self.append_message(sender, payload.content)
            self.play_sound("im_sendmessage.wav")
            self.RequestUserAttention(wx.USER_ATTENTION_INFO)

        elif t == MessageType.CHAT_TYPING:
            payload = ChatTypingPayload(**envelope.payload)
            self.typing_status.SetLabel("Typing…" if payload.is_typing else "")

        elif t == MessageType.CONTACT_REQUEST:
            self.play_sound("misk_chatrequest.wav")
            self._pool.submit(self._bg_load_contacts)

        elif t == MessageType.PRESENCE_BROADCAST:
            payload = PresenceUpdatePayload(**envelope.payload)
            for c in self.contacts:
                if c["id"] == payload.user_id:
                    c["status"] = payload.status.value
                    self.TriggerUpdate()
                    return
            # Unknown contact — full refresh
            self._pool.submit(self._bg_load_contacts)

        elif t == MessageType.CALL_INITIATE:
            payload = CallSignalPayload(**envelope.payload)
            self._incoming_call = payload
            self.play_sound("call_ring_active.wav" if self.is_calling else "call_ring1.wav",
                            loop=True)
            sender_name = next(
                (c["display_name"] for c in self.contacts if c["id"] == payload.sender_id),
                "Someone",
            )
            self.RequestUserAttention(wx.USER_ATTENTION_ERROR)
            res = wx.MessageBox(
                f"Skype: {sender_name} is calling. Answer?", "Incoming Call", wx.YES_NO
            )
            if res == wx.YES:
                self.AnswerCall(payload)
            else:
                self.ws_client.send_envelope(
                    Envelope(type=MessageType.CALL_REJECT, payload=payload.model_dump())
                )
                self.stop_looping_sound()

        elif t == MessageType.CALL_CONNECTING:
            self.play_sound("call_connecting.wav", loop=True)

        elif t == MessageType.CALL_ACCEPT:
            self._call_timer.Stop()
            self.stop_looping_sound()
            self.message_history.AppendText("Call accepted.\n")
            self.call_btn.SetLabel("Hang Up")
            self.audio_engine.start(self.udp_client.send_audio)

        elif t == MessageType.CALL_REJECT:
            self._call_timer.Stop()
            self.message_history.AppendText("Call rejected.\n")
            self.stop_call()

        elif t == MessageType.CALL_HANGUP:
            self.message_history.AppendText("Peer hung up.\n")
            self.stop_call()

    def on_ws_disconnect(self):
        if not self._alive:
            return
        logger.warning("WebSocket disconnected")
        self.message_history.AppendText("\n[Disconnected from server]\n")
