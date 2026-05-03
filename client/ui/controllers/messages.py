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


_REACTION_TEXT: dict[str, str] = {
    "👍": "thumbed this",
    "🤣": "laughed at this",
    "😂": "laughed at this",
    "❤️": "loved this",
    "😮": "was wowed by this",
    "😢": "cried at this",
    "😡": "disliked this",
    "🔥": "found this fire",
    "🎉": "celebrated this",
    "😊": "liked this",
}

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


def _last_seen_str(raw: str | None) -> str:
    """Format a last_seen ISO timestamp as 'Xs/Xm/Xh/Xd/Xy ago'."""
    if not raw:
        return "unknown"
    try:
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        diff = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
        if diff < 60:
            return f"{int(diff)}s ago"
        elif diff < 3600:
            return f"{int(diff / 60)}m ago"
        elif diff < 86400:
            return f"{int(diff / 3600)}h ago"
        elif diff < 31_536_000:
            return f"{int(diff / 86400)}d ago"
        else:
            return f"{int(diff / 31_536_000)}y ago"
    except Exception:
        return "unknown"


def _parse_reply(content: str):
    """If content is a reply, return (orig_sender, orig_content, reply_text). Else None."""
    if not content.startswith("[Reply to "):
        return None
    try:
        end = content.index("]", 10)
        header = content[10:end]
        rest = content[end + 2:]   # skip "]\n"
        if ": " in header:
            sender, quoted = header.split(": ", 1)
            return sender, quoted, rest
    except Exception:
        pass
    return None


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
        # Update view-profile button label
        status = contact.get("status", "")
        if status == "ONLINE":
            seen = "Online"
        else:
            seen = f"Last seen {_last_seen_str(contact.get('last_seen'))}"
        owner.view_profile_btn.SetLabel(
            f"View {contact.get('username', contact['display_name'])}'s Profile — {seen}"
        )
        owner._show_view(owner.VIEW_MESSAGES)
        owner.send_btn.Enable(False)
        self.cancel_reply()
        # Clear unread count for this contact and update title + list
        owner._unread_counts.pop(contact["id"], None)
        owner._update_title()
        owner.contacts_controller.update_list()
        limit = owner.settings.message_history_limit
        owner._load_seq += 1
        owner._pool.submit(self._bg_load_messages, contact["id"], owner._load_seq, limit)
        owner.session_service.send_read_receipt(contact["id"])

    def _bg_load_messages(self, conv_id: str, seq: int, limit: int = 50):
        messages = self.owner.data_service.get_messages(conv_id, limit=limit)
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
            # Skip reaction signals — they annotate other messages, not new items
            content = message.get("content", "")
            if content.startswith("[react:") and content.endswith("]"):
                continue
            is_mine = message["sender_id"] == my_id
            sender = "You" if is_mine else cname
            verb = "sent" if is_mine else "received"
            ts_raw = message.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(
                    str(ts_raw).replace("Z", "+00:00")
                )
                # SQLite stores utcnow() as a naive string — attach UTC so
                # .astimezone() converts correctly to the user's local time.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                dt = dt.astimezone()
            except Exception:
                dt = None
            ts_str = _ts_full(dt)
            entry = {
                "sender":    sender,
                "content":   message["content"],
                "dt":        dt,
                "is_mine":   is_mine,
                "msg_id":    message.get("id", ""),
                "delivered": bool(is_mine and message.get("delivered_at")),
                "read":      bool(is_mine and message.get("read_at")),
            }
            owner._message_items.append(entry)
            owner.message_list.Append(
                self._item_text(entry)
            )
        pending = owner._pending_call_records.pop(owner.current_conversation_id, [])
        for entry in pending:
            self.append_item(entry)

    def _item_text(self, entry: dict) -> str:
        sender  = entry["sender"]
        verb    = "sent" if entry["is_mine"] else "received"
        ts      = _ts_full(entry["dt"])
        content = entry["content"]
        reply   = _parse_reply(content)
        display = (
            f"(↩ Replying to {reply[0]}) {reply[2]}" if reply else content
        )
        # Delivery / read receipt indicator (only on sent messages)
        if entry.get("is_mine"):
            if entry.get("read"):
                receipt = "  ✓✓ Read"
            elif entry.get("delivered"):
                receipt = "  ✓✓"
            else:
                receipt = "  ✓"
        else:
            receipt = ""
        reactions = entry.get("reactions", "")
        return f"{sender}: {display}  {verb} on {ts}{receipt}{reactions}"

    def append_item(self, entry: dict, scroll: bool = True):
        owner = self.owner
        entry.setdefault("read", False)
        owner._message_items.append(entry)
        owner.message_list.Append(self._item_text(entry))
        if scroll:
            owner.message_list.SetSelection(owner.message_list.GetCount() - 1)

    def mark_conversation_delivered(self):
        """Advance sent messages to ✓✓ (delivered)."""
        owner = self.owner
        for idx, item in enumerate(owner._message_items):
            if item.get("is_mine") and not item.get("delivered") and not item.get("read"):
                item["delivered"] = True
                owner.message_list.SetString(idx, self._item_text(item))

    def mark_conversation_read(self):
        """Advance sent messages to ✓✓ Read."""
        owner = self.owner
        for idx, item in enumerate(owner._message_items):
            if item.get("is_mine") and not item.get("read"):
                item["read"]      = True
                item["delivered"] = True
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
            owner.Bind(wx.EVT_MENU, lambda e, em=emoji: self.send_reaction(em, idx), item)
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
        if idx >= len(owner._message_items):
            return
        entry = owner._message_items[idx]
        owner._reply_to_entry = entry
        preview = entry["content"][:80] + ("…" if len(entry["content"]) > 80 else "")
        owner.reply_lbl.SetLabel(
            f"↩ Replying to a message from {entry['sender']}: \"{preview}\""
        )
        owner.reply_bar.Show()
        owner.reply_bar.GetParent().Layout()
        wx.CallAfter(owner.message_input.SetFocus)

    def cancel_reply(self, event=None):
        owner = self.owner
        owner._reply_to_entry = None
        if hasattr(owner, "reply_bar"):
            owner.reply_bar.Hide()
            owner.reply_bar.GetParent().Layout()

    def view_contact_profile(self, event=None):
        owner = self.owner
        contact = owner.selected_contact
        if not contact:
            return
        status = contact.get("status", "OFFLINE").capitalize()
        seen   = (
            "Currently online"
            if contact.get("status") == "ONLINE"
            else f"Last seen {_last_seen_str(contact.get('last_seen'))}"
        )
        mood = contact.get("mood_message", "")
        lines = [
            f"Name:      {contact.get('display_name', '')}",
            f"Username:  {contact.get('username', '')}",
            f"Status:    {status}",
            f"           {seen}",
        ]
        if mood:
            lines.append(f"Mood:      {mood}")
        wx.MessageBox(
            "\n".join(lines),
            f"{contact.get('display_name', 'Contact')}'s Profile",
            wx.OK | wx.ICON_INFORMATION,
            owner,
        )

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

    def send_reaction(self, emoji: str, idx: int = -1):
        owner = self.owner
        if not owner.current_conversation_id:
            return
        # Annotate the targeted message locally
        if 0 <= idx < len(owner._message_items):
            item = owner._message_items[idx]
            verb = _REACTION_TEXT.get(emoji, f"reacted with {emoji}")
            annotation = f"  {emoji} You {verb}"
            item["reactions"] = item.get("reactions", "") + annotation
            owner.message_list.SetString(idx, self._item_text(item))
        # Send the reaction signal directly — bypassing send() so it does NOT
        # appear as a new entry in the message list.
        owner.session_service.send_message(
            owner.current_conversation_id, f"[react:{emoji}]"
        )
        owner._last_message_times[owner.current_conversation_id] = datetime.datetime.now()
        owner.play_sound("msg_react.wav")

    def apply_incoming_reaction(self, emoji: str, sender_name: str):
        """Append a peer's reaction to the most recent message sent by the local user."""
        owner = self.owner
        verb = _REACTION_TEXT.get(emoji, f"reacted with {emoji}")
        annotation = f"  {emoji} {sender_name} {verb}"
        # Find the last message sent by the local user to annotate
        for idx in range(len(owner._message_items) - 1, -1, -1):
            item = owner._message_items[idx]
            if item.get("is_mine"):
                item["reactions"] = item.get("reactions", "") + annotation
                owner.message_list.SetString(idx, self._item_text(item))
                return

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

        # Wrap with reply header if the user is replying to a message
        reply_entry = getattr(owner, "_reply_to_entry", None)
        if reply_entry and not override_content:
            orig = reply_entry["content"][:120]
            content = f"[Reply to {reply_entry['sender']}: {orig}]\n{content}"
            self.cancel_reply()

        owner.session_service.send_message(owner.current_conversation_id, content)
        owner._last_message_times[owner.current_conversation_id] = datetime.datetime.now()
        if not override_content:
            owner.message_input.Clear()
            owner.send_btn.Enable(False)
        entry = {
            "sender": "You",
            "content": content,
            "dt": datetime.datetime.now(),
            "is_mine": True,
            "msg_id": "",
            "delivered": False,
            "read": False,
        }
        self.append_item(entry, scroll=True)
        owner.play_sound("im_sendmsg.wav")

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
        # Keep Send button in sync with whether the input has content
        has_text = bool(owner.message_input.GetValue().strip())
        owner.send_btn.Enable(has_text)
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
