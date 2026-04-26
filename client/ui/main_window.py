"""Main chat window — accessibility-first redesign.

Three full-window views switched via wx.Simplebook:
  VIEW_CONTACTS (0): Contact/Recents list  (default)
  VIEW_MESSAGES (1): Conversation          (hidden until Send IM)
  VIEW_CALL     (2): Active call controls  (hidden until in a call)

Keyboard contract
─────────────────
Alt+1          → Recents view
Alt+2          → Contacts view
Enter on item  → Audio call
Shift+F10/App  → Context menu
Esc (messages) → Back to contacts
Ctrl+1…0       → Read last 10 messages aloud (requires accessible_output2)
"""

import os
import threading
import datetime
import wx
import wx.adv
import structlog
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from ..network.api_client import APIClient
from ..network.ws_client   import WSClient
from shared.models import (
    Envelope, MessageType,
    ChatMessagePayload, CallSignalPayload,
    ChatTypingPayload, PresenceUpdatePayload,
    SettingsPayload,
)
from .settings       import SettingsDialog
from .find_people    import FindPeopleDialog
from .profile_dialog import ProfileDialog

logger = structlog.get_logger()

# ── Optional screen-reader output ────────────────────────────────────────────
try:
    from accessible_output2.outputs.auto import Auto as _AO2
    _ao2 = _AO2()
    AO2_AVAILABLE = True
except Exception:
    _ao2 = None
    AO2_AVAILABLE = False

# ── Palette (Skype 7-inspired) ────────────────────────────────────────────────
_SB_BG     = wx.Colour(30,  58,  91)
_SB_HDR    = wx.Colour(20,  45,  72)
_SB_TEXT   = wx.WHITE
_SB_SUB    = wx.Colour(170, 205, 235)
_BLUE      = wx.Colour(0,  120, 212)
_WHITE     = wx.WHITE
_LIGHT     = wx.Colour(245, 245, 245)
_TEXT      = wx.Colour(32,  31,  30)
_GRAY      = wx.Colour(96,  94,  92)
_GREEN     = wx.Colour(0,  150,  80)
_RED       = wx.Colour(196,  49,  75)

# ── Reaction emojis ───────────────────────────────────────────────────────────
_REACTIONS = [
    ("👍 Thumbs Up",                     "👍"),
    ("🤣 Rolling on the Floor Laughing", "🤣"),
    ("😂 Face with Tears of Joy",        "😂"),
    ("❤️ Heart",                         "❤️"),
    ("😮 Wow",                           "😮"),
    ("😢 Sad",                           "😢"),
    ("😡 Angry",                         "😡"),
    ("🔥 Fire",                          "🔥"),
    ("🎉 Party",                         "🎉"),
    ("😊 Smiling Face",                  "😊"),
]


def _ts_full(dt: datetime.datetime | None) -> str:
    """Format a datetime as 'Sunday, April 26, 2026 at 1:11 PM'."""
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%A, %B %d, %Y at %I:%M %p").replace(" 0", " ")


def _ts_hm(dt: datetime.datetime | None) -> str:
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%H:%M")


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
        self.api_client = api_client
        self.ws_client  = ws_client
        self.user_data  = user_data
        self.settings   = SettingsPayload()

        self.contacts:        list      = []
        self.search_results:  list      = []
        self.is_searching:    bool      = False
        self.selected_contact:dict|None = None
        self.current_conversation_id: str|None = None

        from ..audio.engine    import AudioEngine
        from ..network.udp_client import UDPClient
        self.audio_engine = AudioEngine()
        self.udp_client   = UDPClient("127.0.0.1", 9000)
        self.is_calling   = False
        self.active_session_id: UUID|None = None
        self.looping_sound = None
        self._call_minimized = False

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

        self.ws_client.on_message_callback   = self.on_ws_message
        self.ws_client.on_disconnect_callback = self.on_ws_disconnect

        self._build_ui()
        self.CreateMenus()
        self.CreateStatusBar()
        self.SetStatusText("Ready")
        self.Centre()
        self.SetupShortcuts()
        self._pool.submit(self._bg_load_contacts)

    # ── Shortcuts ─────────────────────────────────────────────────────

    def SetupShortcuts(self):
        ID_ANSWER  = wx.NewIdRef()
        ID_HANGUP  = wx.NewIdRef()
        ID_RECENTS = wx.NewIdRef()
        ID_CONTACTS= wx.NewIdRef()
        # Ctrl+1…0 → read last 10 messages
        self._read_ids = [wx.NewIdRef() for _ in range(10)]

        self.Bind(wx.EVT_MENU, lambda e: self._answer_if_ringing(),                       id=ID_ANSWER)
        self.Bind(wx.EVT_MENU, lambda e: self.HangUp() if self.is_calling else None,      id=ID_HANGUP)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_contact_mode("recents"),            id=ID_RECENTS)
        self.Bind(wx.EVT_MENU, lambda e: self._switch_contact_mode("contacts"),           id=ID_CONTACTS)
        for i, rid in enumerate(self._read_ids):
            self.Bind(wx.EVT_MENU, lambda e, idx=i: self._read_message(idx), id=rid)

        accel = [
            (wx.ACCEL_ALT,  wx.WXK_PAGEUP,   ID_ANSWER),
            (wx.ACCEL_ALT,  wx.WXK_PAGEDOWN, ID_HANGUP),
            (wx.ACCEL_ALT,  ord('1'),         ID_RECENTS),
            (wx.ACCEL_ALT,  ord('2'),         ID_CONTACTS),
            (wx.ACCEL_CTRL, ord(','),         wx.ID_PREFERENCES),
        ]
        for i, rid in enumerate(self._read_ids):
            key = ord('0') if i == 9 else ord(str(i + 1))
            accel.append((wx.ACCEL_CTRL, key, rid))
        self.SetAcceleratorTable(wx.AcceleratorTable(accel))

    def _answer_if_ringing(self):
        if hasattr(self, "_incoming_call"):
            self.AnswerCall(self._incoming_call)

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
        rec_item  = view.Append(wx.ID_ANY, "&Recent Conversations\tAlt+1")
        cont_item = view.Append(wx.ID_ANY, "&Contacts\tAlt+2")

        help_ = wx.Menu()
        help_.Append(wx.ID_HELP,  "&Help Topics")
        help_.Append(wx.ID_ABOUT, "&About Skype Reborn")

        bar.Append(skype, "&Skype")
        bar.Append(view,  "&View")
        bar.Append(help_, "&Help")
        self.SetMenuBar(bar)

        self.Bind(wx.EVT_MENU, lambda e: self.Close(),                          id=wx.ID_EXIT)
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
        self._book.AddPage(self._build_contact_view(), "Contacts")
        self._book.AddPage(self._build_message_view(), "Messages")
        self._book.AddPage(self._build_call_view(),    "Call")

        root.Add(self._book, 1, wx.EXPAND)
        self.panel.SetSizer(root)

        # Timers
        self._call_timer     = wx.Timer(self)
        self._presence_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_call_timeout,              self._call_timer)
        self.Bind(wx.EVT_TIMER, lambda e: self.UpdateContactList(), self._presence_timer)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_MENU,  self.OnSettings, id=wx.ID_PREFERENCES)

    # ── Contact view (page 0) ─────────────────────────────────────────

    def _build_contact_view(self) -> wx.Panel:
        page = wx.Panel(self._book, name="Contact View")
        page.SetBackgroundColour(_SB_BG)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Profile strip
        prof = wx.Panel(page, name="Profile Strip")
        prof.SetBackgroundColour(_SB_HDR)
        prof_sz = wx.BoxSizer(wx.HORIZONTAL)

        av_path = os.path.join("assets", "images", "profile_anonymous.png")
        if os.path.exists(av_path):
            img = wx.Image(av_path).Scale(40, 40, wx.IMAGE_QUALITY_HIGH)
            self.my_avatar = wx.StaticBitmap(prof, bitmap=wx.Bitmap(img), name="My Avatar")
            prof_sz.Add(self.my_avatar, 0, wx.ALL, 10)

        info = wx.BoxSizer(wx.VERTICAL)
        self.profile_name = wx.StaticText(prof, label=self.user_data.get("username",""), name="Username")
        f = self.profile_name.GetFont(); f.SetPointSize(10); f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.profile_name.SetFont(f); self.profile_name.SetForegroundColour(_SB_TEXT)
        info.Add(self.profile_name, 0)

        self.my_status_label = wx.StaticText(prof, label="Online", name="My Status")
        sf = self.my_status_label.GetFont(); sf.SetPointSize(8)
        self.my_status_label.SetFont(sf); self.my_status_label.SetForegroundColour(_SB_SUB)
        info.Add(self.my_status_label, 0)

        prof_sz.Add(info, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        prof.SetSizer(prof_sz); prof.SetMinSize((-1, 60))
        sz.Add(prof, 0, wx.EXPAND)

        # Action buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.profile_btn = wx.Button(page, label="View Profile", name="View Profile")
        self.find_btn    = wx.Button(page, label="Find People",  name="Find People")
        btn_row.Add(self.profile_btn, 1, wx.EXPAND | wx.ALL, 6)
        btn_row.Add(self.find_btn,   1, wx.EXPAND | wx.ALL, 6)
        sz.Add(btn_row, 0, wx.EXPAND)

        # Search bar
        self.search_ctrl = wx.SearchCtrl(page, name="Search")
        self.search_ctrl.SetHint("Search people…")
        self.search_ctrl.ShowSearchButton(True)
        self.search_ctrl.ShowCancelButton(True)
        sz.Add(self.search_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Recents / Contacts tab buttons
        tab_row = wx.BoxSizer(wx.HORIZONTAL)
        self.recents_btn  = wx.Button(page, label="Recent Conversations", name="Recents Tab")
        self.contacts_btn = wx.Button(page, label="Contacts",             name="Contacts Tab")
        tab_row.Add(self.recents_btn,  1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 3)
        tab_row.Add(self.contacts_btn, 1, wx.EXPAND | wx.RIGHT | wx.BOTTOM,           3)
        sz.Add(tab_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Section label
        self.list_label = wx.StaticText(page, label="CONTACTS", name="Section Label")
        self.list_label.SetForegroundColour(_SB_SUB)
        lf = self.list_label.GetFont(); lf.SetPointSize(8); self.list_label.SetFont(lf)
        sz.Add(self.list_label, 0, wx.LEFT | wx.TOP, 8)

        # Contact ListBox
        self.contact_list = wx.ListBox(page, style=wx.LB_SINGLE | wx.BORDER_NONE, name="Contact List")
        self.contact_list.SetBackgroundColour(_SB_BG)
        self.contact_list.SetForegroundColour(_SB_TEXT)
        self.contact_list.SetToolTip(
            "Press Enter to call. Press Shift+F10 or right-click for more options."
        )
        sz.Add(self.contact_list, 1, wx.EXPAND)

        page.SetSizer(sz)

        # Bindings
        self.profile_btn.Bind(wx.EVT_BUTTON, self.OnViewProfile)
        self.find_btn.Bind(wx.EVT_BUTTON,    self.OnFindPeople)
        self.recents_btn.Bind(wx.EVT_BUTTON, lambda e: self._switch_contact_mode("recents"))
        self.contacts_btn.Bind(wx.EVT_BUTTON,lambda e: self._switch_contact_mode("contacts"))
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.OnSearch)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self._on_search_cancel)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER,            self.OnSearch)
        self.search_ctrl.Bind(wx.EVT_TEXT,                  self.OnSearchText)
        self.contact_list.Bind(wx.EVT_LISTBOX,        self.OnContactSelected)
        self.contact_list.Bind(wx.EVT_KEY_DOWN,       self._on_contact_key)
        self.contact_list.Bind(wx.EVT_CONTEXT_MENU,   self._on_contact_context_menu)
        return page

    # ── Message view (page 1) ─────────────────────────────────────────

    def _build_message_view(self) -> wx.Panel:
        page = wx.Panel(self._book, name="Message View")
        page.SetBackgroundColour(_WHITE)
        sz = wx.BoxSizer(wx.VERTICAL)

        # Header: back button + contact name
        hdr = wx.BoxSizer(wx.HORIZONTAL)
        self.back_btn = wx.Button(page, label="← Back to Contacts (Esc)", name="Back Button")
        self.msg_header = wx.StaticText(page, label="", name="Conversation Header")
        f = self.msg_header.GetFont(); f.SetPointSize(11); f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.msg_header.SetFont(f)
        hdr.Add(self.back_btn,  0, wx.ALL, 6)
        hdr.Add(self.msg_header,1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sz.Add(hdr, 0, wx.EXPAND)
        sz.Add(wx.StaticLine(page), 0, wx.EXPAND)

        # Message list (first in tab order)
        self.message_list = wx.ListBox(
            page, style=wx.LB_SINGLE | wx.BORDER_SIMPLE, name="Message List"
        )
        self.message_list.SetToolTip(
            "Messages. Shift+F10 or right-click for reply, react, copy, delete."
        )
        sz.Add(self.message_list, 1, wx.EXPAND | wx.ALL, 4)

        # Message input
        self.message_input = wx.TextCtrl(
            page,
            style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
            name="Message Input",
        )
        self.message_input.SetHint("Type a message…  Enter = send, Shift+Enter = newline")
        self.message_input.SetMinSize((-1, 40))
        sz.Add(self.message_input, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        # Buttons row
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.voice_btn  = wx.Button(page, label="Voice Message",  name="Voice Message")
        self.emoji_btn  = wx.Button(page, label="Send Emoticon",  name="Send Emoticon")
        self.attach_btn = wx.Button(page, label="Add Attachment", name="Add Attachment")
        self.send_btn   = wx.Button(page, label="Send",           name="Send")
        self.send_btn.SetBackgroundColour(_BLUE)
        self.send_btn.SetForegroundColour(_WHITE)
        btn_row.Add(self.voice_btn,  0, wx.ALL, 4)
        btn_row.Add(self.emoji_btn,  0, wx.ALL, 4)
        btn_row.Add(self.attach_btn, 0, wx.ALL, 4)
        btn_row.AddStretchSpacer()
        btn_row.Add(self.send_btn,   0, wx.ALL, 4)
        sz.Add(btn_row, 0, wx.EXPAND)

        page.SetSizer(sz)

        self.back_btn.Bind(wx.EVT_BUTTON,      lambda e: self._show_view(self.VIEW_CONTACTS))
        self.send_btn.Bind(wx.EVT_BUTTON,      self.OnSend)
        self.voice_btn.Bind(wx.EVT_BUTTON,     lambda e: self._not_supported("Voice messaging"))
        self.emoji_btn.Bind(wx.EVT_BUTTON,     self._on_emoji)
        self.attach_btn.Bind(wx.EVT_BUTTON,    self.OnSendFile)
        self.message_input.Bind(wx.EVT_TEXT,   self.OnTyping)
        self.message_input.Bind(wx.EVT_KEY_DOWN, self._on_msg_key)
        self.message_list.Bind(wx.EVT_CONTEXT_MENU, self._on_message_context_menu)
        self.message_list.Bind(wx.EVT_KEY_DOWN, self._on_msg_list_key)
        page.Bind(wx.EVT_KEY_DOWN, self._on_msg_view_key)
        return page

    # ── Call view (page 2) ────────────────────────────────────────────

    def _build_call_view(self) -> wx.Panel:
        page = wx.Panel(self._book, name="Call View")
        page.SetBackgroundColour(wx.Colour(18, 38, 58))
        sz = wx.BoxSizer(wx.VERTICAL)
        sz.AddStretchSpacer()

        self.call_contact_lbl = wx.StaticText(page, label="", style=wx.ALIGN_CENTER, name="Call Contact")
        cf = self.call_contact_lbl.GetFont(); cf.SetPointSize(16); cf.SetWeight(wx.FONTWEIGHT_BOLD)
        self.call_contact_lbl.SetFont(cf); self.call_contact_lbl.SetForegroundColour(_WHITE)
        sz.Add(self.call_contact_lbl, 0, wx.ALIGN_CENTER | wx.BOTTOM, 6)

        self.call_status_text = wx.StaticText(page, label="", style=wx.ALIGN_CENTER, name="Call Status")
        sf2 = self.call_status_text.GetFont(); sf2.SetPointSize(11)
        self.call_status_text.SetFont(sf2); self.call_status_text.SetForegroundColour(_SB_SUB)
        sz.Add(self.call_status_text, 0, wx.ALIGN_CENTER | wx.BOTTOM, 32)

        def _call_btn(label, name, colour=None):
            b = wx.Button(page, label=label, name=name)
            b.SetMinSize((-1, 44))
            if colour:
                b.SetBackgroundColour(colour)
                b.SetForegroundColour(_WHITE)
            sz.Add(b, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
            return b

        self.end_call_btn   = _call_btn("End Call",               "End Call",     _RED)
        self.mute_btn       = _call_btn("Mute Microphone",        "Mute",         _BLUE)
        self.add_part_btn   = _call_btn("Add Participant",        "Add Participant")
        self.camera_btn     = _call_btn("Turn on Camera",         "Camera")
        self.minimize_btn   = _call_btn("Minimize Call Window",   "Minimize Call")

        sz.AddStretchSpacer()
        page.SetSizer(sz)

        self.end_call_btn.Bind(wx.EVT_BUTTON,  lambda e: self.HangUp())
        self.mute_btn.Bind(wx.EVT_BUTTON,      self._toggle_mute)
        self.add_part_btn.Bind(wx.EVT_BUTTON,  lambda e: self._not_supported("Group calls"))
        self.camera_btn.Bind(wx.EVT_BUTTON,    lambda e: self._not_supported("Video calls"))
        self.minimize_btn.Bind(wx.EVT_BUTTON,  self._on_minimize_call)
        return page

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
        self.UpdateContactList()
        wx.CallAfter(self.contact_list.SetFocus)

    def _on_minimize_call(self, event):
        self._call_minimized = True
        self._show_view(self.VIEW_CONTACTS)

    # ═══════════════════════════════════════════════════════════════════
    # CLOSE
    # ═══════════════════════════════════════════════════════════════════

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

    # ═══════════════════════════════════════════════════════════════════
    # CONTACTS
    # ═══════════════════════════════════════════════════════════════════

    def _bg_load_contacts(self):
        contacts = self.api_client.get_contacts()
        wx.CallAfter(self._on_contacts_loaded, contacts)

    def _on_contacts_loaded(self, contacts):
        if not self._alive: return
        self.contacts = contacts
        if not self.is_searching:
            self.UpdateContactList()

    def TriggerUpdate(self):
        self._presence_timer.StartOnce(500)

    def UpdateContactList(self):
        if self.is_searching:
            self.list_label.SetLabel("SEARCH RESULTS")
            items = []
            for u in self.search_results:
                mood = u.get("mood_message", "")
                tag  = "  [Bot]" if u.get("is_bot") else ""
                items.append(f"{u['display_name']}{tag}, {u['status'].title()}{', ' + mood if mood else ''}")
            if not items:
                items = ["No results found."]
        else:
            mode_label = "RECENT CONVERSATIONS" if self._contact_mode == "recents" else "CONTACTS"
            self.list_label.SetLabel(mode_label)
            self.contacts.sort(key=lambda c: (c["status"] != "ONLINE", c["display_name"]))
            items = []
            for c in self.contacts:
                mood = c.get("mood_message", "")
                items.append(
                    f"{c['display_name']}, {c['status'].title()}{', ' + mood if mood else ''}"
                )
            if not items:
                items = ["No contacts yet. Use Find People to add contacts."]

        if list(self.contact_list.GetStrings()) == items:
            return

        sel_id = self.selected_contact["id"] if self.selected_contact else None
        self.contact_list.Freeze()
        self.contact_list.Set(items)
        if sel_id and not self.is_searching:
            for i, c in enumerate(self.contacts):
                if c["id"] == sel_id:
                    self.contact_list.SetSelection(i); break
        self.contact_list.Thaw()

    def OnContactSelected(self, event):
        idx = self.contact_list.GetSelection()
        if idx == wx.NOT_FOUND: return
        if self.is_searching:
            if idx < len(self.search_results):
                self.selected_contact = self.search_results[idx]
            return
        if idx >= len(self.contacts): return
        self.selected_contact = self.contacts[idx]
        self.SetStatusText(self.selected_contact["display_name"])

    # ── Contact keyboard ──────────────────────────────────────────────

    def _on_contact_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_RETURN:
            if self.selected_contact:
                self.OnCall(None)
        elif key == wx.WXK_ESCAPE:
            self.search_ctrl.Clear()
            self.is_searching = False
            self.UpdateContactList()
        else:
            event.Skip()

    # ── Contact context menu ──────────────────────────────────────────

    def _on_contact_context_menu(self, event):
        idx = self.contact_list.GetSelection()
        if idx == wx.NOT_FOUND:
            event.Skip(); return
        if not self.is_searching and idx < len(self.contacts):
            self.selected_contact = self.contacts[idx]
        elif self.is_searching and idx < len(self.search_results):
            self.selected_contact = self.search_results[idx]
        if not self.selected_contact:
            event.Skip(); return

        menu = wx.Menu()

        call_sub = wx.Menu()
        audio_item = call_sub.Append(wx.ID_ANY, "Audio Call\tEnter")
        video_item = call_sub.Append(wx.ID_ANY, "Video Call")
        menu.AppendSubMenu(call_sub, "Call")

        im_item     = menu.Append(wx.ID_ANY, "Send IM")
        menu.Append(wx.ID_ANY, "Add to Group").Enable(False)
        menu.Append(wx.ID_ANY, "Report to Admins").Enable(False)
        block_item  = menu.Append(wx.ID_ANY, "Block This Contact")

        self.Bind(wx.EVT_MENU, lambda e: self.OnCall(None),                  audio_item)
        self.Bind(wx.EVT_MENU, lambda e: self._not_supported("Video calls"), video_item)
        self.Bind(wx.EVT_MENU, lambda e: self._open_im(),                    im_item)
        self.Bind(wx.EVT_MENU, lambda e: self._block_contact(),              block_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def _open_im(self):
        if not self.selected_contact: return
        self.current_conversation_id = self.selected_contact["id"]
        self.msg_header.SetLabel(
            f"Conversation with {self.selected_contact['display_name']}"
        )
        self._show_view(self.VIEW_MESSAGES)
        self._load_seq += 1
        self._pool.submit(self._bg_load_messages, self.selected_contact["id"], self._load_seq)

    def _block_contact(self):
        if not self.selected_contact: return
        name = self.selected_contact["display_name"]
        if wx.MessageBox(
            f"Block {name}? You will no longer receive messages from them.",
            "Block Contact", wx.YES_NO | wx.ICON_WARNING, self
        ) == wx.YES:
            self.SetStatusText(f"{name} blocked.")

    # ── Search ────────────────────────────────────────────────────────

    def OnSearch(self, event):
        query = self.search_ctrl.GetValue().strip()
        if not query:
            self.is_searching = False; self.UpdateContactList(); return
        self.is_searching = True
        self._search_seq += 1; seq = self._search_seq
        self._pool.submit(self._bg_search, query, seq)

    def _bg_search(self, query: str, seq: int):
        results = self.api_client.search_users(query)
        wx.CallAfter(self._on_search_done, query, seq, results)

    def _on_search_done(self, query: str, seq: int, results):
        if not self._alive or seq != self._search_seq: return
        self.search_results = results
        self.UpdateContactList()
        wx.CallAfter(self.contact_list.SetFocus)

    def OnSearchText(self, event):
        if not self.search_ctrl.GetValue():
            self.is_searching = False; self.UpdateContactList()

    def _on_search_cancel(self, event):
        self.search_ctrl.Clear(); self.is_searching = False; self.UpdateContactList()

    # ═══════════════════════════════════════════════════════════════════
    # MESSAGES
    # ═══════════════════════════════════════════════════════════════════

    def _bg_load_messages(self, conv_id: str, seq: int):
        messages = self.api_client.get_messages(conv_id)
        wx.CallAfter(self._on_messages_loaded, seq, messages)

    def _on_messages_loaded(self, seq: int, messages):
        if not self._alive or seq != self._load_seq: return
        self._message_items = []
        self.message_list.Clear()
        if not messages: return
        my_id  = self.user_data["user_id"]
        cname  = self.selected_contact["display_name"] if self.selected_contact else "Contact"
        for m in messages:
            is_mine = m["sender_id"] == my_id
            sender  = "You" if is_mine else cname
            verb    = "sent" if is_mine else "received"
            ts_raw  = m.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).astimezone()
            except Exception:
                dt = None
            ts_str = _ts_full(dt)
            entry  = {"sender": sender, "content": m["content"],
                      "dt": dt, "is_mine": is_mine, "msg_id": m.get("id", "")}
            self._message_items.append(entry)
            self.message_list.Append(f"{sender}: {m['content']}  {verb} on {ts_str}")

    def _append_message_item(self, entry: dict):
        sender = entry["sender"]
        verb   = "sent" if entry["is_mine"] else "received"
        ts_str = _ts_full(entry["dt"])
        self._message_items.append(entry)
        self.message_list.Append(f"{sender}: {entry['content']}  {verb} on {ts_str}")
        self.message_list.SetSelection(self.message_list.GetCount() - 1)

    # ── Message keyboard ──────────────────────────────────────────────

    def _on_msg_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_RETURN and not event.ShiftDown():
            content = self.message_input.GetValue().strip()
            if content and self.current_conversation_id:
                self.OnSend(None); return
        event.Skip()

    def _on_msg_view_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._show_view(self.VIEW_CONTACTS)
        else:
            event.Skip()

    def _on_msg_list_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._show_view(self.VIEW_CONTACTS)
        else:
            event.Skip()

    # ── Message context menu ──────────────────────────────────────────

    def _on_message_context_menu(self, event):
        idx = self.message_list.GetSelection()
        if idx == wx.NOT_FOUND: return
        entry = self._message_items[idx] if idx < len(self._message_items) else None

        menu = wx.Menu()
        reply_item  = menu.Append(wx.ID_ANY, "Reply")
        # React submenu
        react_sub = wx.Menu()
        for label, emoji in _REACTIONS:
            item = react_sub.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda e, em=emoji: self._send_reaction(em), item)
        custom_item = react_sub.Append(wx.ID_ANY, "Send Custom Emoji…")
        menu.AppendSubMenu(react_sub, "React")

        menu.Append(wx.ID_ANY, "Edit").Enable(False)
        fwd_item    = menu.Append(wx.ID_ANY, "Forward")
        copy_item   = menu.Append(wx.ID_ANY, "Copy")
        if entry and entry.get("is_mine"):
            del_item = menu.Append(wx.ID_ANY, "Delete")
            self.Bind(wx.EVT_MENU, lambda e: self._delete_message(idx), del_item)

        self.Bind(wx.EVT_MENU, lambda e: self._reply_to(idx),               reply_item)
        self.Bind(wx.EVT_MENU, lambda e: self._not_supported("Forwarding"), fwd_item)
        self.Bind(wx.EVT_MENU, lambda e: self._copy_message(idx),           copy_item)
        self.Bind(wx.EVT_MENU, lambda e: self._custom_emoji(),              custom_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def _reply_to(self, idx: int):
        if idx < len(self._message_items):
            entry = self._message_items[idx]
            quote = f"> {entry['sender']}: {entry['content']}\n"
            self.message_input.SetValue(quote + self.message_input.GetValue())
            wx.CallAfter(self.message_input.SetFocus)

    def _copy_message(self, idx: int):
        if idx < len(self._message_items):
            text = self._message_items[idx]["content"]
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Close()

    def _delete_message(self, idx: int):
        if idx < len(self._message_items):
            self._message_items.pop(idx)
            self.message_list.Delete(idx)

    def _send_reaction(self, emoji: str):
        if self.current_conversation_id:
            self.OnSend(None, override_content=emoji)

    def _custom_emoji(self):
        val = wx.GetTextFromUser("Enter your emoji or text:", "Custom Emoji", "", self)
        if val and self.current_conversation_id:
            self.OnSend(None, override_content=val)

    def _on_emoji(self, event):
        emojis = [em for _, em in _REACTIONS]
        dlg = wx.SingleChoiceDialog(
            self, "Choose an emoticon:", "Send Emoticon",
            [f"{label}  {em}" for label, em in _REACTIONS],
        )
        if dlg.ShowModal() == wx.ID_OK:
            sel = dlg.GetSelection()
            if sel != wx.NOT_FOUND:
                self.OnSend(None, override_content=_REACTIONS[sel][1])
        dlg.Destroy()

    # ── Ctrl+1…0 message reading ──────────────────────────────────────

    def _read_message(self, idx: int):
        """idx 0 = newest, 9 = 10th newest."""
        if not self._message_items: return
        rev_idx = len(self._message_items) - 1 - idx
        if rev_idx < 0: return
        entry = self._message_items[rev_idx]
        verb  = "sent" if entry["is_mine"] else "received"
        ts    = _ts_full(entry.get("dt"))
        text  = f"{entry['sender']}: {entry['content']} {verb} on {ts}"
        if AO2_AVAILABLE and _ao2:
            _ao2.speak(text, interrupt=True)
        self.SetStatusText(text[:120])

    # ── Send ──────────────────────────────────────────────────────────

    def OnSend(self, event, override_content: str|None = None):
        content = override_content or self.message_input.GetValue().strip()
        if not content or not self.current_conversation_id: return
        payload = ChatMessagePayload(
            conversation_id=self.current_conversation_id,
            sender_id=self.user_data["user_id"],
            content=content,
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump())
        )
        if not override_content:
            self.message_input.Clear()
        entry = {
            "sender": "You", "content": content,
            "dt": datetime.datetime.now(), "is_mine": True, "msg_id": "",
        }
        self._append_message_item(entry)
        if self.settings.notification_sounds:
            self.play_sound("im_sendmessage.wav")

    # ── File transfer ─────────────────────────────────────────────────

    def OnSendFile(self, event):
        if not self.current_conversation_id: return
        with wx.FileDialog(self, "Select file to send",
                           wildcard="All files (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL: return
            path = dlg.GetPath()
        filename = os.path.basename(path)
        self._pool.submit(self._bg_upload, path, filename, self.current_conversation_id)

    def _bg_upload(self, path, filename, conv_id):
        try:
            with open(path, "rb") as fh: content = fh.read()
            ok, res = self.api_client.upload_file(conv_id, filename, content)
        except Exception as e:
            ok, res = False, str(e)
        wx.CallAfter(self._on_upload_done, ok, filename, res)

    def _on_upload_done(self, ok, filename, res):
        if not self._alive: return
        msg = f"Sent file: {filename}" if ok else f"Failed to send {filename}: {res}"
        entry = {"sender": "You" if ok else "System", "content": msg,
                 "dt": datetime.datetime.now(), "is_mine": ok, "msg_id": ""}
        self._append_message_item(entry)

    # ── Typing ────────────────────────────────────────────────────────

    def OnTyping(self, event):
        if not self.current_conversation_id: return
        if not self._is_typing:
            self._is_typing = True; self._send_typing(True)
        if self._typing_timer and self._typing_timer.IsRunning():
            self._typing_timer.Restart(3000)
        else:
            self._typing_timer = wx.CallLater(3000, self._on_typing_idle)

    def _on_typing_idle(self):
        self._is_typing = False; self._typing_timer = None; self._send_typing(False)

    def _send_typing(self, is_typing: bool):
        if not self.current_conversation_id: return
        payload = ChatTypingPayload(
            conversation_id=self.current_conversation_id,
            user_id=self.user_data["user_id"], is_typing=is_typing,
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CHAT_TYPING, payload=payload.model_dump())
        )

    # ═══════════════════════════════════════════════════════════════════
    # CALLS
    # ═══════════════════════════════════════════════════════════════════

    def OnCall(self, event):
        if self.is_calling:
            self.HangUp(); return
        if not self.selected_contact: return

        name = self.selected_contact["display_name"]
        self.call_contact_lbl.SetLabel(name)
        self.call_status_text.SetLabel("Calling…")
        self.is_calling = True

        self._show_view(self.VIEW_CALL)
        self.play_sound("call_request_sent.wav")

        self.active_session_id = uuid4()
        payload = CallSignalPayload(
            session_id=str(self.active_session_id),
            target_id=self.selected_contact["id"],
            sender_id=self.user_data["user_id"],
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.CALL_INITIATE, payload=payload.model_dump())
        )
        self.udp_client.start(
            self.active_session_id, self.audio_engine.receive_audio,
            user_id=self.user_data["user_id"],
        )
        self._call_timer.StartOnce(30_000)

    def _on_call_timeout(self, event):
        if self.is_calling:
            self.call_status_text.SetLabel("No answer.")
            self.HangUp()

    def _toggle_mute(self, event=None):
        if self.audio_engine._muted:
            self.audio_engine.unmute()
            self.mute_btn.SetLabel("Mute Microphone")
        else:
            self.audio_engine.mute()
            self.mute_btn.SetLabel("Unmute Microphone")

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
        self.is_calling        = False
        self._call_minimized   = False
        self.mute_btn.SetLabel("Mute Microphone")
        self.play_sound("call_end.wav")
        if hasattr(self, "_incoming_call"): del self._incoming_call
        self._show_view(self.VIEW_CONTACTS)

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

        sender_name = next(
            (c["display_name"] for c in self.contacts if c["id"] == payload.sender_id),
            "Contact"
        )
        self.call_contact_lbl.SetLabel(sender_name)
        self.call_status_text.SetLabel("In call")
        self._show_view(self.VIEW_CALL)

    # ═══════════════════════════════════════════════════════════════════
    # STATUS / PROFILE
    # ═══════════════════════════════════════════════════════════════════

    def _send_presence(self, status_str: str):
        from shared.models import UserStatus
        payload = PresenceUpdatePayload(
            user_id=self.user_data["user_id"],
            status=UserStatus[status_str],
        )
        self.ws_client.send_envelope(
            Envelope(type=MessageType.PRESENCE_UPDATE, payload=payload.model_dump())
        )
        labels = {"ONLINE": "Online", "AWAY": "Away", "BUSY": "Busy", "INVISIBLE": "Invisible"}
        self.my_status_label.SetLabel(labels.get(status_str, status_str.title()))

    def OnViewProfile(self, event):
        dlg = ProfileDialog(self, self.api_client, self.user_data)
        dlg.ShowModal(); dlg.Destroy()

    def OnFindPeople(self, event):
        def do_search(query):
            self.SetStatusText(f"Searching for '{query}'…")
            return self.api_client.search_users(query)
        def do_add(user):
            self.api_client.add_contact(user["username"])
            self.SetStatusText(f"Added {user['display_name']} to contacts")
            self._pool.submit(self._bg_load_contacts)
        dlg = FindPeopleDialog(self, do_search, do_add)
        dlg.ShowModal(); dlg.Destroy()

    def OnSettings(self, event):
        def save_settings(new_settings):
            self.settings = new_settings
            self.SetStatusText("Settings saved")
        dlg = SettingsDialog(self, self.settings, save_settings)
        dlg.ShowModal(); dlg.Destroy()

    # ═══════════════════════════════════════════════════════════════════
    # SOUNDS
    # ═══════════════════════════════════════════════════════════════════

    def play_sound(self, filename: str, loop: bool = False):
        path = os.path.join("assets", "sounds", filename)
        if not os.path.exists(path): return None
        sound = wx.adv.Sound(path)
        if not sound.IsOk(): return None
        flags = wx.adv.SOUND_ASYNC | (wx.adv.SOUND_LOOP if loop else 0)
        sound.Play(flags)
        if loop: self.looping_sound = sound
        return sound

    def stop_looping_sound(self):
        wx.adv.Sound.Stop()
        self.looping_sound = None

    # ═══════════════════════════════════════════════════════════════════
    # WEBSOCKET HANDLER
    # ═══════════════════════════════════════════════════════════════════

    def on_ws_message(self, envelope: Envelope):
        if not self._alive: return
        t = envelope.type

        if t == MessageType.CHAT_RECEIVE:
            pl    = ChatMessagePayload(**envelope.payload)
            cname = self.selected_contact["display_name"] if self.selected_contact else "Contact"
            entry = {
                "sender": cname, "content": pl.content,
                "dt": datetime.datetime.now(), "is_mine": False, "msg_id": "",
            }
            if self._current_view == self.VIEW_MESSAGES:
                self._append_message_item(entry)
            if self.settings.notification_sounds:
                self.play_sound("im_sendmessage.wav")
            self.RequestUserAttention(wx.USER_ATTENTION_INFO)

        elif t == MessageType.CHAT_TYPING:
            pl = ChatTypingPayload(**envelope.payload)
            if self._current_view == self.VIEW_MESSAGES and self.selected_contact:
                label = "Typing…" if pl.is_typing else ""
                self.msg_header.SetLabel(
                    f"Conversation with {self.selected_contact['display_name']}"
                    + (f"  —  {label}" if label else "")
                )

        elif t == MessageType.CONTACT_REQUEST:
            self.play_sound("misk_chatrequest.wav")
            self._pool.submit(self._bg_load_contacts)

        elif t == MessageType.PRESENCE_BROADCAST:
            pl = PresenceUpdatePayload(**envelope.payload)
            for c in self.contacts:
                if c["id"] == pl.user_id:
                    c["status"] = pl.status.value
                    self.TriggerUpdate(); return
            self._pool.submit(self._bg_load_contacts)

        elif t == MessageType.CALL_INITIATE:
            pl = CallSignalPayload(**envelope.payload)
            self._incoming_call = pl
            snd = "call_ring_active.wav" if self.is_calling else "call_ring1.wav"
            self.play_sound(snd, loop=True)
            sender_name = next(
                (c["display_name"] for c in self.contacts if c["id"] == pl.sender_id),
                "Someone",
            )
            self.RequestUserAttention(wx.USER_ATTENTION_ERROR)
            res = wx.MessageBox(
                f"{sender_name} is calling you. Answer?",
                "Incoming Call", wx.YES_NO, self,
            )
            if res == wx.YES:
                self.AnswerCall(pl)
            else:
                self.ws_client.send_envelope(
                    Envelope(type=MessageType.CALL_REJECT, payload=pl.model_dump())
                )
                self.stop_looping_sound()

        elif t == MessageType.CALL_CONNECTING:
            self.stop_looping_sound()
            self.call_status_text.SetLabel("Ringing…")
            self.play_sound("call_connecting.wav", loop=True)

        elif t == MessageType.CALL_ACCEPT:
            self._call_timer.Stop()
            self.stop_looping_sound()
            self.call_status_text.SetLabel("In call")
            self.audio_engine.start(self.udp_client.send_audio)

        elif t == MessageType.CALL_REJECT:
            self._call_timer.Stop()
            self.call_status_text.SetLabel("Call rejected.")
            self.stop_call()

        elif t == MessageType.CALL_HANGUP:
            self.call_status_text.SetLabel("Call ended.")
            self.stop_call()

    def on_ws_disconnect(self):
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
