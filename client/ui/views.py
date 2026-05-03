import os

import wx


class _NamedAccessible(wx.Accessible):
    """Gives an explicit accessible name to any control that lacks one."""
    def __init__(self, ctrl, label):
        super().__init__(ctrl)
        self._label = label

    def GetName(self, childId):
        if childId == 0:
            return wx.ACC_OK, self._label
        return wx.ACC_NOT_IMPLEMENTED, ""

_SB_BG = wx.Colour(30, 58, 91)
_SB_HDR = wx.Colour(20, 45, 72)
_SB_TEXT = wx.WHITE
_SB_SUB = wx.Colour(170, 205, 235)
_BLUE = wx.Colour(0, 120, 212)
_WHITE = wx.WHITE
_RED = wx.Colour(196, 49, 75)


def build_contact_view(owner, book: wx.Simplebook) -> wx.Panel:
    page = wx.Panel(book, name="Contact View")
    page.SetBackgroundColour(_SB_BG)
    sz = wx.BoxSizer(wx.VERTICAL)

    btn_row = wx.BoxSizer(wx.HORIZONTAL)
    owner.profile_btn = wx.Button(page, label="View Profile", name="View Profile")
    owner.find_btn = wx.Button(page, label="Find People", name="Find People")
    btn_row.Add(owner.profile_btn, 1, wx.EXPAND | wx.ALL, 6)
    btn_row.Add(owner.find_btn, 1, wx.EXPAND | wx.ALL, 6)
    sz.Add(btn_row, 0, wx.EXPAND)

    search_lbl = wx.StaticText(page, label="Search contacts:", name="Search Label")
    search_lbl.SetForegroundColour(_SB_SUB)
    sz.Add(search_lbl, 0, wx.LEFT | wx.TOP, 6)
    owner.search_ctrl = wx.TextCtrl(
        page,
        style=wx.TE_PROCESS_ENTER,
        name="Search contacts",
    )
    owner.search_ctrl.SetHint("Search people...  Enter to search, Esc to clear")
    owner.search_ctrl.SetAccessible(_NamedAccessible(owner.search_ctrl, "Search contacts"))
    sz.Add(owner.search_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

    tab_row = wx.BoxSizer(wx.HORIZONTAL)
    owner.recents_btn = wx.Button(page, label="Recent Conversations", name="Recents Tab")
    owner.contacts_btn = wx.Button(page, label="Contacts", name="Contacts Tab")
    tab_row.Add(owner.recents_btn, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 3)
    tab_row.Add(owner.contacts_btn, 1, wx.EXPAND | wx.RIGHT | wx.BOTTOM, 3)
    sz.Add(tab_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

    owner.list_label = wx.StaticText(page, label="CONTACTS", name="Section Label")
    owner.list_label.SetForegroundColour(_SB_SUB)
    lf = owner.list_label.GetFont()
    lf.SetPointSize(8)
    owner.list_label.SetFont(lf)
    sz.Add(owner.list_label, 0, wx.LEFT | wx.TOP, 8)

    owner.contact_list = wx.ListBox(
        page, style=wx.LB_SINGLE | wx.BORDER_NONE, name="Contact List"
    )
    owner.contact_list.SetBackgroundColour(_SB_BG)
    owner.contact_list.SetForegroundColour(_SB_TEXT)
    owner.contact_list.SetToolTip(
        "Press Enter or double-click to open chat. Press Shift+F10 or right-click for more options."
    )
    sz.Add(owner.contact_list, 1, wx.EXPAND)

    page.SetSizer(sz)

    owner.profile_btn.Bind(wx.EVT_BUTTON, owner.OnViewProfile)
    owner.find_btn.Bind(wx.EVT_BUTTON, owner.OnFindPeople)
    owner.recents_btn.Bind(wx.EVT_BUTTON, lambda e: owner._switch_contact_mode("recents"))
    owner.contacts_btn.Bind(wx.EVT_BUTTON, lambda e: owner._switch_contact_mode("contacts"))
    owner.search_ctrl.Bind(wx.EVT_TEXT_ENTER, owner.contacts_controller.search)
    owner.search_ctrl.Bind(wx.EVT_TEXT, owner.contacts_controller.on_search_text)
    owner.search_ctrl.Bind(
        wx.EVT_KEY_DOWN,
        lambda e: (
            owner.contacts_controller.on_search_cancel(e)
            if e.GetKeyCode() == wx.WXK_ESCAPE
            else e.Skip()
        ),
    )
    owner.contact_list.Bind(wx.EVT_LISTBOX, owner.contacts_controller.on_selected)
    owner.contact_list.Bind(wx.EVT_LISTBOX_DCLICK, owner.contacts_controller.on_open_requested)
    owner.contact_list.Bind(wx.EVT_KEY_DOWN, owner.contacts_controller.on_key)
    owner.contact_list.Bind(wx.EVT_CONTEXT_MENU, owner.contacts_controller.on_context_menu)
    return page


def build_message_view(owner, book: wx.Simplebook) -> wx.Panel:
    page = wx.Panel(book, name="Message View")
    page.SetBackgroundColour(_WHITE)
    sz = wx.BoxSizer(wx.VERTICAL)

    # ── Header row: Back | View Profile | Conversation title ──────────
    hdr = wx.BoxSizer(wx.HORIZONTAL)
    owner.back_btn = wx.Button(page, label="Back to Contacts (Esc)", name="Back Button")
    owner.view_profile_btn = wx.Button(page, label="View Profile", name="View Profile Button")
    owner.msg_header = wx.StaticText(page, label="", name="Conversation Header")
    f = owner.msg_header.GetFont()
    f.SetPointSize(11)
    f.SetWeight(wx.FONTWEIGHT_BOLD)
    owner.msg_header.SetFont(f)
    hdr.Add(owner.back_btn, 0, wx.ALL, 6)
    hdr.Add(owner.view_profile_btn, 0, wx.TOP | wx.BOTTOM | wx.RIGHT, 6)
    hdr.Add(owner.msg_header, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
    sz.Add(hdr, 0, wx.EXPAND)
    sz.Add(wx.StaticLine(page), 0, wx.EXPAND)

    # ── Message list ─────────────────────────────────────────────────
    owner.message_list = wx.ListBox(
        page, style=wx.LB_SINGLE | wx.BORDER_SIMPLE, name="Message List"
    )
    owner.message_list.SetToolTip(
        "Messages. Shift+F10 or right-click for reply, react, copy, delete."
    )
    owner.message_list.SetAccessible(_NamedAccessible(owner.message_list, "Message List"))
    sz.Add(owner.message_list, 1, wx.EXPAND | wx.ALL, 4)

    # ── Reply bar (hidden until the user hits Reply) ─────────────────
    owner.reply_bar = wx.Panel(page)
    owner.reply_bar.SetBackgroundColour(wx.Colour(232, 240, 254))
    rb_sz = wx.BoxSizer(wx.HORIZONTAL)
    owner.reply_lbl = wx.StaticText(
        owner.reply_bar, label="", name="Reply Context"
    )
    rb_lf = owner.reply_lbl.GetFont()
    rb_lf.SetPointSize(9)
    owner.reply_lbl.SetFont(rb_lf)
    owner.reply_lbl.SetForegroundColour(wx.Colour(0, 80, 160))
    owner.reply_cancel_btn = wx.Button(
        owner.reply_bar, label="✕", size=(26, 26), name="Cancel Reply"
    )
    rb_sz.Add(owner.reply_lbl, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
    rb_sz.Add(owner.reply_cancel_btn, 0, wx.ALL, 2)
    owner.reply_bar.SetSizer(rb_sz)
    owner.reply_bar.Hide()
    sz.Add(owner.reply_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

    # ── Input area ───────────────────────────────────────────────────
    msg_lbl = wx.StaticText(page, label="Message:", name="Message Label")
    sz.Add(msg_lbl, 0, wx.LEFT | wx.TOP, 4)
    owner.message_input = wx.TextCtrl(
        page,
        style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
        name="Message",
    )
    owner.message_input.SetHint("Type a message...  Enter = send, Shift+Enter = newline")
    owner.message_input.SetMinSize((-1, 40))
    owner.message_input.SetAccessible(_NamedAccessible(owner.message_input, "Message"))
    sz.Add(owner.message_input, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

    btn_row = wx.BoxSizer(wx.HORIZONTAL)
    owner.voice_btn  = wx.Button(page, label="Voice Message",   name="Voice Message")
    owner.emoji_btn  = wx.Button(page, label="Send Emoticon",   name="Send Emoticon")
    owner.attach_btn = wx.Button(page, label="Add Attachment",  name="Add Attachment")
    owner.send_btn   = wx.Button(page, label="Send",            name="Send")
    owner.send_btn.SetBackgroundColour(_BLUE)
    owner.send_btn.SetForegroundColour(_WHITE)
    owner.send_btn.Enable(False)   # disabled until the input has content
    btn_row.Add(owner.voice_btn,  0, wx.ALL, 4)
    btn_row.Add(owner.emoji_btn,  0, wx.ALL, 4)
    btn_row.Add(owner.attach_btn, 0, wx.ALL, 4)
    btn_row.AddStretchSpacer()
    btn_row.Add(owner.send_btn,   0, wx.ALL, 4)
    sz.Add(btn_row, 0, wx.EXPAND)

    page.SetSizer(sz)

    owner.back_btn.Bind(wx.EVT_BUTTON, lambda e: owner._show_view(owner.VIEW_CONTACTS))
    owner.view_profile_btn.Bind(wx.EVT_BUTTON, owner.messages_controller.view_contact_profile)
    owner.reply_cancel_btn.Bind(wx.EVT_BUTTON, owner.messages_controller.cancel_reply)
    owner.send_btn.Bind(wx.EVT_BUTTON, owner.messages_controller.send)
    owner.voice_btn.Bind(wx.EVT_BUTTON, lambda e: owner._not_supported("Voice messaging"))
    owner.emoji_btn.Bind(wx.EVT_BUTTON, owner.messages_controller.on_emoji)
    owner.attach_btn.Bind(wx.EVT_BUTTON, owner.messages_controller.send_file)
    owner.message_input.Bind(wx.EVT_TEXT, owner.messages_controller.on_typing)
    owner.message_input.Bind(wx.EVT_KEY_DOWN, owner.messages_controller.on_msg_key)
    owner.message_list.Bind(wx.EVT_CONTEXT_MENU, owner.messages_controller.on_context_menu)
    owner.message_list.Bind(wx.EVT_KEY_DOWN, owner.messages_controller.on_escape_key)
    page.Bind(wx.EVT_KEY_DOWN, owner.messages_controller.on_escape_key)
    return page


def build_call_view(owner, book: wx.Simplebook) -> wx.Panel:
    page = wx.Panel(book, name="Call View")
    page.SetBackgroundColour(wx.Colour(18, 38, 58))
    sz = wx.BoxSizer(wx.VERTICAL)
    sz.AddStretchSpacer()

    owner.call_contact_lbl = wx.StaticText(
        page, label="", style=wx.ALIGN_CENTER, name="Call Contact"
    )
    cf = owner.call_contact_lbl.GetFont()
    cf.SetPointSize(16)
    cf.SetWeight(wx.FONTWEIGHT_BOLD)
    owner.call_contact_lbl.SetFont(cf)
    owner.call_contact_lbl.SetForegroundColour(_WHITE)
    sz.Add(owner.call_contact_lbl, 0, wx.ALIGN_CENTER | wx.BOTTOM, 6)

    owner.call_status_text = wx.StaticText(
        page, label="", style=wx.ALIGN_CENTER, name="Call Status"
    )
    sf2 = owner.call_status_text.GetFont()
    sf2.SetPointSize(11)
    owner.call_status_text.SetFont(sf2)
    owner.call_status_text.SetForegroundColour(_SB_SUB)
    sz.Add(owner.call_status_text, 0, wx.ALIGN_CENTER | wx.BOTTOM, 32)

    def _call_btn(label, name, colour=None):
        button = wx.Button(page, label=label, name=name)
        button.SetMinSize((-1, 44))
        if colour:
            button.SetBackgroundColour(colour)
            button.SetForegroundColour(_WHITE)
        sz.Add(button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 20)
        return button

    owner.end_call_btn = _call_btn("End Call", "End Call", _RED)
    owner.mute_btn = _call_btn("Mute Microphone", "Mute", _BLUE)
    owner.add_part_btn = _call_btn("Add Participant", "Add Participant")
    owner.camera_btn = _call_btn("Turn on Camera", "Camera")
    owner.minimize_btn = _call_btn("Minimize Call Window", "Minimize Call")

    sz.AddStretchSpacer()
    page.SetSizer(sz)

    owner.end_call_btn.Bind(wx.EVT_BUTTON, lambda e: owner.calls_controller.hang_up())
    owner.mute_btn.Bind(wx.EVT_BUTTON, owner.calls_controller.toggle_mute)
    owner.add_part_btn.Bind(wx.EVT_BUTTON, lambda e: owner._not_supported("Group calls"))
    owner.camera_btn.Bind(wx.EVT_BUTTON, lambda e: owner._not_supported("Video calls"))
    owner.minimize_btn.Bind(wx.EVT_BUTTON, owner._on_minimize_call)
    return page
