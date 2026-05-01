import wx


class ContactsController:
    def __init__(self, owner):
        self.owner = owner

    def update_list(self):
        owner = self.owner
        if owner.is_searching:
            owner.list_label.SetLabel("SEARCH RESULTS")
            items = []
            for user in owner.search_results:
                mood = user.get("mood_message", "")
                tag = "  [Bot]" if user.get("is_bot") else ""
                items.append(
                    f"{user['display_name']}{tag}, {user['status'].title()}{', ' + mood if mood else ''}"
                )
            if not items:
                items = ["No results found."]
        else:
            mode_label = (
                "RECENT CONVERSATIONS"
                if owner._contact_mode == "recents"
                else "CONTACTS"
            )
            owner.list_label.SetLabel(mode_label)
            owner.contacts.sort(key=lambda c: (c["status"] != "ONLINE", c["display_name"]))
            items = []
            for contact in owner.contacts:
                mood = contact.get("mood_message", "")
                items.append(
                    f"{contact['display_name']}, {contact['status'].title()}{', ' + mood if mood else ''}"
                )
            if not items:
                items = ["No contacts yet. Use Find People to add contacts."]

        if list(owner.contact_list.GetStrings()) == items:
            return

        sel_id = owner.selected_contact["id"] if owner.selected_contact else None
        owner.contact_list.Freeze()
        owner.contact_list.Set(items)
        if sel_id and not owner.is_searching:
            for i, contact in enumerate(owner.contacts):
                if contact["id"] == sel_id:
                    owner.contact_list.SetSelection(i)
                    break
        owner.contact_list.Thaw()

    def on_selected(self, event):
        owner = self.owner
        idx = owner.contact_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        if owner.is_searching:
            if idx < len(owner.search_results):
                owner.selected_contact = owner.search_results[idx]
            return
        if idx >= len(owner.contacts):
            return
        owner.selected_contact = owner.contacts[idx]
        owner.SetStatusText(owner.selected_contact["display_name"])

    def on_key(self, event):
        owner = self.owner
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.open_selected_contact()
        elif key == wx.WXK_ESCAPE:
            owner.search_ctrl.Clear()
            owner.is_searching = False
            self.update_list()
        else:
            event.Skip()

    def on_open_requested(self, event):
        self.open_selected_contact()

    def open_selected_contact(self) -> bool:
        owner = self.owner
        idx = owner.contact_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return False
        if owner.is_searching:
            if idx < len(owner.search_results):
                owner.selected_contact = owner.search_results[idx]
        elif idx < len(owner.contacts):
            owner.selected_contact = owner.contacts[idx]

        if owner.selected_contact:
            owner.SetStatusText(owner.selected_contact["display_name"])
            owner.messages_controller.open_conversation(owner.selected_contact)
            return True
        return False

    def on_context_menu(self, event):
        owner = self.owner
        idx = owner.contact_list.GetSelection()
        if idx == wx.NOT_FOUND:
            event.Skip()
            return
        if not owner.is_searching and idx < len(owner.contacts):
            owner.selected_contact = owner.contacts[idx]
        elif owner.is_searching and idx < len(owner.search_results):
            owner.selected_contact = owner.search_results[idx]
        if not owner.selected_contact:
            event.Skip()
            return

        menu = wx.Menu()
        call_sub = wx.Menu()
        audio_item = call_sub.Append(wx.ID_ANY, "Audio Call")
        video_item = call_sub.Append(wx.ID_ANY, "Video Call")
        menu.AppendSubMenu(call_sub, "Call")

        im_item = menu.Append(wx.ID_ANY, "Send IM")
        menu.Append(wx.ID_ANY, "Add to Group").Enable(False)
        menu.Append(wx.ID_ANY, "Report to Admins").Enable(False)
        block_item = menu.Append(wx.ID_ANY, "Block This Contact")

        owner.Bind(wx.EVT_MENU, lambda e: owner.calls_controller.start_call(), audio_item)
        owner.Bind(wx.EVT_MENU, lambda e: owner._not_supported("Video calls"), video_item)
        owner.Bind(
            wx.EVT_MENU,
            lambda e: owner.messages_controller.open_conversation(owner.selected_contact),
            im_item,
        )
        owner.Bind(wx.EVT_MENU, lambda e: self.block_contact(), block_item)

        owner.PopupMenu(menu)
        menu.Destroy()

    def block_contact(self):
        owner = self.owner
        if not owner.selected_contact:
            return
        name = owner.selected_contact["display_name"]
        if (
            wx.MessageBox(
                f"Block {name}? You will no longer receive messages from them.",
                "Block Contact",
                wx.YES_NO | wx.ICON_WARNING,
                owner,
            )
            == wx.YES
        ):
            owner.SetStatusText(f"{name} blocked.")

    def search(self, event):
        owner = self.owner
        query = owner.search_ctrl.GetValue().strip()
        if not query:
            owner.is_searching = False
            self.update_list()
            return
        owner.is_searching = True
        owner._search_seq += 1
        seq = owner._search_seq
        owner._pool.submit(self._bg_search, query, seq)

    def _bg_search(self, query: str, seq: int):
        results = self.owner.data_service.search_users(query)
        wx.CallAfter(self._on_search_done, query, seq, results)

    def _on_search_done(self, query: str, seq: int, results):
        owner = self.owner
        if not owner._alive or seq != owner._search_seq:
            return
        owner.search_results = results
        self.update_list()
        wx.CallAfter(owner.contact_list.SetFocus)

    def on_search_text(self, event):
        owner = self.owner
        if not owner.search_ctrl.GetValue():
            owner.is_searching = False
            self.update_list()

    def on_search_cancel(self, event):
        owner = self.owner
        owner.search_ctrl.Clear()
        owner.is_searching = False
        self.update_list()
