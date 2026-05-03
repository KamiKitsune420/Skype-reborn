import datetime
import os

import wx

try:
    from accessible_output2.outputs.auto import Auto as _AO2
    _ao2 = _AO2()
    AO2_AVAILABLE = True
except Exception:
    _ao2 = None
    AO2_AVAILABLE = False


_REACTIONS = [
    ("👍 Thumbs Up", "👍"),
    ("🤣 Rolling on the Floor Laughing", "🤣"),
    ("😂 Face with Tears of Joy", "😂"),
    ("❤️ Heart", "❤️"),
    ("😮 Wow", "😮"),
    ("😢 Sad", "😢"),
    ("😡 Angry", "😡"),
    ("🔥 Fire", "🔥"),
    ("🎉 Party", "🎉"),
    ("😊 Smiling Face", "😊"),
]


def _ts_full(dt: datetime.datetime | None) -> str:
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%A, %B %d, %Y at %I:%M %p").replace(" 0", " ")


class MessagesController:
    def __init__(self, owner):
        self.owner = owner

    def open_conversation(self, contact: dict | None):
        owner = self.owner
        if not contact:
            return
        owner.current_conversation_id = contact["id"]
        owner.selected_contact = contact
        owner.msg_header.SetLabel(f"Conversation with {contact['display_name']}")
        owner._show_view(owner.VIEW_MESSAGES)
        owner._load_seq += 1
        owner._pool.submit(self._bg_load_messages, contact["id"], owner._load_seq)
        # Tell the peer we've read their messages
        owner.session_service.send_read_receipt(contact["id"])

    def _bg_load_messages(self, conv_id: str, seq: int):
        messages = self.owner.data_service.get_messages(conv_id)
        wx.CallAfter(self._on_messages_loaded, seq, messages)

    def _on_messages_loaded(self, seq: int, messages):
        owner = self.owner
        if not owner._alive or seq != owner._load_seq:
            return
        owner._message_items = []
        owner.message_list.Clear()
        if not messages:
            pending = owner._pending_call_records.pop(owner.current_conversation_id, [])
            for entry in pending:
                self.append_item(entry)
            return
        my_id = owner.user_data["user_id"]
        cname = owner.selected_contact["display_name"] if owner.selected_contact else "Contact"
        for message in messages:
            is_mine = message["sender_id"] == my_id
            sender = "You" if is_mine else cname
            verb = "sent" if is_mine else "received"
            ts_raw = message.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(
                    str(ts_raw).replace("Z", "+00:00")
                ).astimezone()
            except Exception:
                dt = None
            ts_str = _ts_full(dt)
            entry = {
                "sender": sender,
                "content": message["content"],
                "dt": dt,
                "is_mine": is_mine,
                "msg_id": message.get("id", ""),
            }
            owner._message_items.append(entry)
            owner.message_list.Append(
                f"{sender}: {message['content']}  {verb} on {ts_str}"
            )
        pending = owner._pending_call_records.pop(owner.current_conversation_id, [])
        for entry in pending:
            self.append_item(entry)

    def _item_text(self, entry: dict) -> str:
        sender = entry["sender"]
        verb   = "sent" if entry["is_mine"] else "received"
        ts     = _ts_full(entry["dt"])
        read   = "  ✓ Read" if entry.get("read") else ""
        return f"{sender}: {entry['content']}  {verb} on {ts}{read}"

    def append_item(self, entry: dict):
        owner = self.owner
        entry.setdefault("read", False)
        owner._message_items.append(entry)
        owner.message_list.Append(self._item_text(entry))
        owner.message_list.SetSelection(owner.message_list.GetCount() - 1)

    def mark_conversation_read(self):
        """Mark all sent messages in the current conversation as read and refresh their display."""
        owner = self.owner
        for idx, item in enumerate(owner._message_items):
            if item.get("is_mine") and not item.get("read"):
                item["read"] = True
                owner.message_list.SetString(idx, self._item_text(item))

    def append_call_record(
        self,
        peer_id: str,
        peer_name: str,
        is_incoming: bool,
        duration: datetime.timedelta,
    ):
        owner = self.owner
        total_secs = int(duration.total_seconds())
        mins, secs = divmod(total_secs, 60)
        dur_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        now = datetime.datetime.now()
        sender = peer_name if is_incoming else "You"
        entry = {
            "sender": sender,
            "content": f"\U0001f4de Audio call · {dur_str}",
            "dt": now,
            "is_mine": not is_incoming,
            "msg_id": "",
        }
        is_open = (
            owner.current_conversation_id == peer_id
            and owner._current_view == owner.VIEW_MESSAGES
        )
        if is_open:
            self.append_item(entry)
        else:
            owner._pending_call_records.setdefault(peer_id, []).append(entry)

    def on_msg_key(self, event):
        owner = self.owner
        key = event.GetKeyCode()
        if key == wx.WXK_RETURN and not event.ShiftDown():
            content = owner.message_input.GetValue().strip()
            if content and owner.current_conversation_id:
                self.send(None)
                return
        event.Skip()

    def on_escape_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.owner._back_from_chat()
        else:
            event.Skip()

    def on_context_menu(self, event):
        owner = self.owner
        idx = owner.message_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        entry = owner._message_items[idx] if idx < len(owner._message_items) else None

        menu = wx.Menu()
        reply_item = menu.Append(wx.ID_ANY, "Reply")
        react_sub = wx.Menu()
        for label, emoji in _REACTIONS:
            item = react_sub.Append(wx.ID_ANY, label)
            owner.Bind(wx.EVT_MENU, lambda e, em=emoji: self.send_reaction(em), item)
        custom_item = react_sub.Append(wx.ID_ANY, "Send Custom Emoji...")
        menu.AppendSubMenu(react_sub, "React")

        menu.Append(wx.ID_ANY, "Edit").Enable(False)
        fwd_item = menu.Append(wx.ID_ANY, "Forward")
        copy_item = menu.Append(wx.ID_ANY, "Copy")
        if entry and entry.get("is_mine"):
            del_item = menu.Append(wx.ID_ANY, "Delete")
            owner.Bind(wx.EVT_MENU, lambda e: self.delete_message(idx), del_item)

        owner.Bind(wx.EVT_MENU, lambda e: self.reply_to(idx), reply_item)
        owner.Bind(wx.EVT_MENU, lambda e: owner._not_supported("Forwarding"), fwd_item)
        owner.Bind(wx.EVT_MENU, lambda e: self.copy_message(idx), copy_item)
        owner.Bind(wx.EVT_MENU, lambda e: self.custom_emoji(), custom_item)

        owner.PopupMenu(menu)
        menu.Destroy()

    def reply_to(self, idx: int):
        owner = self.owner
        if idx < len(owner._message_items):
            entry = owner._message_items[idx]
            quote = f"> {entry['sender']}: {entry['content']}\n"
            owner.message_input.SetValue(quote + owner.message_input.GetValue())
            wx.CallAfter(owner.message_input.SetFocus)

    def copy_message(self, idx: int):
        owner = self.owner
        if idx < len(owner._message_items):
            text = owner._message_items[idx]["content"]
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Close()

    def delete_message(self, idx: int):
        owner = self.owner
        if idx < len(owner._message_items):
            owner._message_items.pop(idx)
            owner.message_list.Delete(idx)

    def send_reaction(self, emoji: str):
        if self.owner.current_conversation_id:
            self.send(None, override_content=emoji)

    def custom_emoji(self):
        owner = self.owner
        val = wx.GetTextFromUser("Enter your emoji or text:", "Custom Emoji", "", owner)
        if val and owner.current_conversation_id:
            self.send(None, override_content=val)

    def on_emoji(self, event):
        dlg = wx.SingleChoiceDialog(
            self.owner,
            "Choose an emoticon:",
            "Send Emoticon",
            [f"{label}  {emoji}" for label, emoji in _REACTIONS],
        )
        if dlg.ShowModal() == wx.ID_OK:
            sel = dlg.GetSelection()
            if sel != wx.NOT_FOUND:
                self.send(None, override_content=_REACTIONS[sel][1])
        dlg.Destroy()

    def read_message(self, idx: int):
        owner = self.owner
        if not owner._message_items:
            return
        rev_idx = len(owner._message_items) - 1 - idx
        if rev_idx < 0:
            return
        entry = owner._message_items[rev_idx]
        verb = "sent" if entry["is_mine"] else "received"
        ts = _ts_full(entry.get("dt"))
        text = f"{entry['sender']}: {entry['content']} {verb} on {ts}"
        if AO2_AVAILABLE and _ao2:
            _ao2.speak(text, interrupt=True)
        owner.SetStatusText(text[:120])

    def send(self, event, override_content: str | None = None):
        owner = self.owner
        content = override_content or owner.message_input.GetValue().strip()
        if not content or not owner.current_conversation_id:
            return
        owner.session_service.send_message(owner.current_conversation_id, content)
        if not override_content:
            owner.message_input.Clear()
        entry = {
            "sender": "You",
            "content": content,
            "dt": datetime.datetime.now(),
            "is_mine": True,
            "msg_id": "",
            "read": False,
        }
        self.append_item(entry)
        if owner.settings.notification_sounds:
            owner.play_sound("im_sendmessage.wav")

    def send_file(self, event):
        owner = self.owner
        if not owner.current_conversation_id:
            return
        with wx.FileDialog(
            owner,
            "Select file to send",
            wildcard="All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            path = dlg.GetPath()
        filename = os.path.basename(path)
        owner._pool.submit(
            self._bg_upload, path, filename, owner.current_conversation_id
        )

    def _bg_upload(self, path, filename, conv_id):
        try:
            with open(path, "rb") as fh:
                content = fh.read()
            ok, res = self.owner.data_service.upload_file(conv_id, filename, content)
        except Exception as exc:
            ok, res = False, str(exc)
        wx.CallAfter(self._on_upload_done, ok, filename, res)

    def _on_upload_done(self, ok, filename, res):
        if not self.owner._alive:
            return
        msg = f"Sent file: {filename}" if ok else f"Failed to send {filename}: {res}"
        entry = {
            "sender": "You" if ok else "System",
            "content": msg,
            "dt": datetime.datetime.now(),
            "is_mine": ok,
            "msg_id": "",
        }
        self.append_item(entry)

    def on_typing(self, event):
        owner = self.owner
        if not owner.current_conversation_id:
            return
        if not owner._is_typing:
            owner._is_typing = True
            self._send_typing(True)
        if owner._typing_timer and owner._typing_timer.IsRunning():
            owner._typing_timer.Restart(3000)
        else:
            owner._typing_timer = wx.CallLater(3000, self.on_typing_idle)

    def on_typing_idle(self):
        owner = self.owner
        owner._is_typing = False
        owner._typing_timer = None
        self._send_typing(False)

    def _send_typing(self, is_typing: bool):
        owner = self.owner
        if not owner.current_conversation_id:
            return
        owner.session_service.send_typing(owner.current_conversation_id, is_typing)
