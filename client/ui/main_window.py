import wx
import wx.adv
import os
import asyncio
from wxasync import AsyncBind
from ..network.api_client import APIClient
from ..network.ws_client import WSClient
from shared.models import Envelope, MessageType, ChatMessagePayload, CallSignalPayload, ChatTypingPayload
from uuid import UUID, uuid4

class MainWindow(wx.Frame):
    def __init__(self, api_client: APIClient, ws_client: WSClient, user_data: dict):
        super().__init__(None, title=f"Skype™ Reborn - {user_data.get('username', 'User')}", 
                         size=(1000, 700), name="Skype Main Window")
        self.api_client = api_client
        self.ws_client = ws_client
        self.user_data = user_data
        
        self.contacts = [] 
        self.search_results = []
        self.is_searching = False
        self.selected_contact = None 
        self.current_conversation_id = None
        
        # Audio
        from ..audio.engine import AudioEngine
        from ..network.udp_client import UDPClient
        self.audio_engine = AudioEngine()
        self.udp_client = UDPClient("127.0.0.1", 9000)
        self.is_calling = False
        self.active_session_id = None
        self.looping_sound = None

        self.InitUI()
        self.CreateMenus()
        self.Centre()
        
        # Accelerators (Hotkeys)
        self.SetupShortcuts()

        self.ws_client.on_message_callback = self.on_ws_message
        asyncio.create_task(self.LoadContacts())
        self.typing_task = None
        self._is_currently_typing = False
        self._update_timer = None
        self._selection_task = None

    def TriggerUpdate(self):
        # Debounce UI updates to prevent lag during rapid status changes
        if self._update_timer:
            self._update_timer.cancel()
        
        async def do_update():
            await asyncio.sleep(0.5)
            self.UpdateContactList()
            
        self._update_timer = asyncio.create_task(do_update())

    def SetupShortcuts(self):
        ID_ANSWER = wx.NewIdRef()
        ID_HANGUP = wx.NewIdRef()
        ID_SEARCH_FOCUS = wx.NewIdRef()
        ID_RECENTS = wx.NewIdRef()
        ID_CONTACTS = wx.NewIdRef()
        
        self.Bind(wx.EVT_MENU, self.OnGlobalAnswer, id=ID_ANSWER)
        self.Bind(wx.EVT_MENU, self.OnGlobalHangUp, id=ID_HANGUP)
        self.Bind(wx.EVT_MENU, lambda e: self.search_ctrl.SetFocus(), id=ID_SEARCH_FOCUS)
        self.Bind(wx.EVT_MENU, lambda e: self.OnRecentsFocus(e), id=ID_RECENTS)
        self.Bind(wx.EVT_MENU, lambda e: self.OnContactsFocus(e), id=ID_CONTACTS)

        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_ALT, wx.WXK_PAGEUP, ID_ANSWER),
            (wx.ACCEL_ALT, wx.WXK_PAGEDOWN, ID_HANGUP),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('S'), ID_SEARCH_FOCUS),
            (wx.ACCEL_ALT, ord('1'), ID_RECENTS),
            (wx.ACCEL_ALT, ord('2'), ID_CONTACTS),
            (wx.ACCEL_CTRL, ord(','), wx.ID_PREFERENCES),
        ])
        self.SetAcceleratorTable(accel_tbl)

    def CreateMenus(self):
        menubar = wx.MenuBar()
        
        skype_menu = wx.Menu()
        skype_menu.Append(wx.ID_ANY, "Online &Status")
        skype_menu.Append(wx.ID_PREFERENCES, "S&ettings...\tCtrl+,")
        skype_menu.AppendSeparator()
        skype_menu.Append(wx.ID_EXIT, "E&xit")
        
        contacts_menu = wx.Menu()
        contacts_menu.Append(wx.ID_ANY, "&Add Contact...")
        contacts_menu.Append(wx.ID_ANY, "&Search for Skype Users...\tCtrl+Shift+S")
        
        conversation_menu = wx.Menu()
        conversation_menu.Append(wx.ID_ANY, "&Send File...\tCtrl+Shift+F")
        conversation_menu.Append(wx.ID_ANY, "&Take Snapshot\tCtrl+S")
        
        call_menu = wx.Menu()
        call_menu.Append(wx.ID_ANY, "&Call\tAlt+C")
        call_menu.Append(wx.ID_ANY, "&Hang Up\tAlt+H")
        
        help_menu = wx.Menu()
        help_menu.Append(wx.ID_HELP, "&Help Topics\tCtrl+H")
        help_menu.Append(wx.ID_ABOUT, "&About Skype Reborn")
        
        menubar.Append(skype_menu, "&Skype")
        menubar.Append(contacts_menu, "&Contacts")
        menubar.Append(conversation_menu, "Con&versation")
        menubar.Append(call_menu, "Ca&ll")
        menubar.Append(help_menu, "&Help")
        
        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_EXIT)

    def InitUI(self):
        self.panel = wx.Panel(self, name="Main Panel")
        self.main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left Sidebar
        sidebar = wx.Panel(self.panel, size=(300, -1), style=wx.BORDER_NONE, name="Sidebar Panel")
        sidebar.SetBackgroundColour(wx.Colour(255, 255, 255))
        sidebar_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Profile Section
        profile_panel = wx.Panel(sidebar, name="Profile Panel")
        profile_sizer = wx.BoxSizer(wx.HORIZONTAL)
        avatar_path = os.path.join("assets", "images", "profile_anonymous.png")
        if os.path.exists(avatar_path):
            img = wx.Image(avatar_path, wx.BITMAP_TYPE_ANY).Scale(48, 48, wx.IMAGE_QUALITY_HIGH)
            sbmp = wx.StaticBitmap(profile_panel, -1, wx.Bitmap(img), name="My Avatar")
            profile_sizer.Add(sbmp, 0, wx.ALL, 15)
        
        self.profile_name = wx.StaticText(profile_panel, label=self.user_data.get("username", "User"), name="My Profile Name")
        font = self.profile_name.GetFont()
        font.SetPointSize(11)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.profile_name.SetFont(font)
        
        # Status Dropdown (Simplified)
        self.status_btn = wx.Button(profile_panel, label="▼", size=(20, 20), style=wx.BU_EXACTFIT, name="Change Status Button")
        self.status_btn.SetToolTip("Change your online status")
        # For NVDA, the 'name' parameter usually helps, but we can also set help text
        self.status_btn.SetHelpText("Click to change your online status (Online, Away, Busy, Invisible)")
        
        profile_text_sizer = wx.BoxSizer(wx.VERTICAL)
        profile_text_sizer.Add(self.profile_name, 0)
        
        profile_sizer.Add(profile_text_sizer, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        profile_sizer.Add(self.status_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        profile_panel.SetSizer(profile_sizer)
        sidebar_sizer.Add(profile_panel, 0, wx.EXPAND)
        
        # Search Control
        self.search_label = wx.StaticText(sidebar, label="&Search users", name="Search Label")
        self.search_ctrl = wx.SearchCtrl(sidebar, style=wx.TE_PROCESS_ENTER, name="Global User Search")
        self.search_ctrl.SetDescriptiveText("Search Skype users...")
        sidebar_sizer.Add(self.search_label, 0, wx.LEFT | wx.RIGHT, 10)
        sidebar_sizer.Add(self.search_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # Tabs Placeholder (Recent / Contacts)
        self.tab_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.recents_btn = wx.Button(sidebar, label="&Recent", style=wx.BU_EXACTFIT | wx.BORDER_NONE, name="Recent Chats Tab")
        self.contacts_btn = wx.Button(sidebar, label="&Contacts", style=wx.BU_EXACTFIT | wx.BORDER_NONE, name="Contacts List Tab")
        self.tab_sizer.Add(self.recents_btn, 1, wx.EXPAND)
        self.tab_sizer.Add(self.contacts_btn, 1, wx.EXPAND)
        sidebar_sizer.Add(self.tab_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        self.list_label = wx.StaticText(sidebar, label="CONTACTS", name="List Header Label")
        self.list_label.SetForegroundColour(wx.Colour(120, 120, 120))
        sidebar_sizer.Add(self.list_label, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 10)
        
        # Optimized ListBox
        self.contact_list = wx.ListBox(sidebar, style=wx.LB_SINGLE | wx.BORDER_NONE, name="Contact and Search List")
        self.contact_list.SetBackgroundColour(wx.WHITE)
        sidebar_sizer.Add(self.contact_list, 1, wx.EXPAND)
        
        sidebar.SetSizer(sidebar_sizer)
        self.main_sizer.Add(sidebar, 0, wx.EXPAND)
        
        # Right Area (Chat)
        self.chat_area = wx.Panel(self.panel, name="Conversation Panel")
        self.chat_area.SetBackgroundColour(wx.WHITE)
        chat_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Chat Header
        self.header_panel = wx.Panel(self.chat_area, name="Conversation Header")
        self.header_panel.SetBackgroundColour(wx.Colour(250, 250, 250))
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.chat_header = wx.StaticText(self.header_panel, label="Welcome to Skype™", name="Active Chat Contact Name")
        self.chat_header.SetFont(font)
        header_sizer.Add(self.chat_header, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 20)
        
        self.typing_status = wx.StaticText(self.header_panel, label="", name="Typing Notification")
        self.typing_status.SetForegroundColour(wx.Colour(128, 128, 128))
        header_sizer.Add(self.typing_status, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 20)
        self.header_panel.SetSizer(header_sizer)
        chat_sizer.Add(self.header_panel, 0, wx.EXPAND)
        
        # Message History
        self.message_history = wx.TextCtrl(self.chat_area, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.BORDER_NONE, name="Chat Message History")
        chat_sizer.Add(self.message_history, 1, wx.EXPAND | wx.ALL, 5)
        
        # Call Panel (Hidden by default)
        self.call_panel = wx.Panel(self.chat_area, name="In-Call Status Panel")
        self.call_panel.SetBackgroundColour(wx.Colour(0, 175, 240)) # Skype Blue
        call_psizer = wx.BoxSizer(wx.HORIZONTAL)
        self.call_status_text = wx.StaticText(self.call_panel, label="Calling...", style=wx.ALIGN_CENTER)
        self.call_status_text.SetForegroundColour(wx.WHITE)
        self.call_status_text.SetFont(font)
        call_psizer.Add(self.call_status_text, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)
        self.call_panel.SetSizer(call_psizer)
        chat_sizer.Add(self.call_panel, 0, wx.EXPAND)
        self.call_panel.Hide()

        # Input Area
        self.input_panel = wx.Panel(self.chat_area, name="Message Entry Area")
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.file_btn = wx.Button(self.input_panel, label="+", size=(30, 30), name="Send File Button")
        input_sizer.Add(self.file_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)

        # Message Input Label (Hidden visually but available for NVDA)
        self.msg_label = wx.StaticText(self.input_panel, label="&Message")
        input_sizer.Add(self.msg_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)

        self.message_input = wx.TextCtrl(self.input_panel, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE, name="Message Input Box")
        self.message_input.SetHint("Type a message here...")
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 10)
        
        self.btn_sizer = wx.BoxSizer(wx.VERTICAL)
        self.send_btn = wx.Button(self.input_panel, label="&Send", name="Send Message Button")
        self.call_btn = wx.Button(self.input_panel, label="&Call", name="Start Voice Call Button")
        self.btn_sizer.Add(self.send_btn, 0, wx.BOTTOM, 5)
        self.btn_sizer.Add(self.call_btn, 0)
        input_sizer.Add(self.btn_sizer, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        
        self.input_panel.SetSizer(input_sizer)
        chat_sizer.Add(self.input_panel, 0, wx.EXPAND)
        
        self.chat_area.SetSizer(chat_sizer)
        self.main_sizer.Add(self.chat_area, 1, wx.EXPAND)
        
        # Default State: Hide Conversation
        self.chat_area.Hide()
        
        self.panel.SetSizer(self.main_sizer)

        # Bindings
        AsyncBind(wx.EVT_BUTTON, self.OnSend, self.send_btn)
        AsyncBind(wx.EVT_BUTTON, self.OnCall, self.call_btn)
        AsyncBind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.OnSearch, self.search_ctrl)
        AsyncBind(wx.EVT_TEXT_ENTER, self.OnSearch, self.search_ctrl)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.OnSearchText)
        
        self.message_input.Bind(wx.EVT_TEXT_ENTER, lambda e: asyncio.create_task(self.OnSend(e)))
        self.message_input.Bind(wx.EVT_TEXT, self.OnTyping)
        self.contact_list.Bind(wx.EVT_LISTBOX, self.OnContactSelected)
        
        self.recents_btn.Bind(wx.EVT_BUTTON, self.OnRecentsFocus)
        self.contacts_btn.Bind(wx.EVT_BUTTON, self.OnContactsFocus)
        self.status_btn.Bind(wx.EVT_BUTTON, self.OnStatusMenu)
        AsyncBind(wx.EVT_BUTTON, self.OnSendFile, self.file_btn)

    async def OnSendFile(self, event):
        if not self.current_conversation_id: return
        with wx.FileDialog(self, "Select file to send", wildcard="All files (*.*)|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            filename = os.path.basename(path)
            
            self.append_message("System", f"Sending {filename}...")
            with open(path, "rb") as f:
                content = f.read()
                success, res = await self.api_client.upload_file(self.current_conversation_id, filename, content)
                if success:
                    self.append_message("Me", f"Sent a file: {filename}")
                else:
                    self.append_message("System", f"Failed to send file: {res}")

    def OnStatusMenu(self, event):
        menu = wx.Menu()
        statuses = ["ONLINE", "AWAY", "BUSY", "INVISIBLE"]
        for s in statuses:
            item = menu.Append(wx.ID_ANY, s)
            self.Bind(wx.EVT_MENU, lambda e, status=s: asyncio.create_task(self.ChangeStatus(status)), item)
        self.PopupMenu(menu)

    async def ChangeStatus(self, status_str):
        from shared.models import UserStatus, PresenceUpdatePayload
        status_enum = UserStatus[status_str]
        payload = PresenceUpdatePayload(user_id=self.user_data["user_id"], status=status_enum)
        await self.ws_client.send_envelope(Envelope(type=MessageType.PRESENCE_UPDATE, payload=payload.model_dump()))
        logger.info(f"Status changed to {status_str}")

    def OnRecentsFocus(self, event):
        self.is_searching = False
        self.list_label.SetLabel("RECENT CONVERSATIONS")
        self.UpdateContactList() # For now we only have contacts
        self.contact_list.SetFocus()

    def OnContactsFocus(self, event):
        self.is_searching = False
        self.list_label.SetLabel("CONTACTS")
        self.UpdateContactList()
        self.contact_list.SetFocus()

    def play_sound(self, filename, loop=False):
        sound_path = os.path.join("assets", "sounds", filename)
        if os.path.exists(sound_path):
            sound = wx.adv.Sound(sound_path)
            if sound.IsOk():
                flags = wx.adv.SOUND_ASYNC
                if loop: flags |= wx.adv.SOUND_LOOP
                sound.Play(flags)
                if loop: self.looping_sound = sound
                return sound
        return None

    def stop_looping_sound(self):
        wx.adv.Sound.Stop()
        self.looping_sound = None

    async def LoadContacts(self):
        self.contacts = await self.api_client.get_contacts()
        if not self.is_searching:
            self.UpdateContactList()

    def UpdateContactList(self):
        # Only Clear if absolutely necessary or if list length changed significantly
        # For small lists, simple updates are faster and better for screen readers
        
        current_selection = self.contact_list.GetSelection()
        current_items = self.contact_list.GetStrings()
        new_items = []

        if self.is_searching:
            self.list_label.SetLabel("SEARCH RESULTS")
            for u in self.search_results:
                new_items.append(u['display_name'])
        else:
            # Sort contacts: Online first, then offline
            sorted_contacts = sorted(self.contacts, key=lambda x: (x['status'] != 'ONLINE', x['display_name']))
            self.contacts = sorted_contacts
            for c in self.contacts:
                status_char = "●" if c['status'] == 'ONLINE' else "○"
                new_items.append(f"{status_char} {c['display_name']}")

        if current_items != new_items:
            self.contact_list.Freeze()
            self.contact_list.Set(new_items) # Set is more efficient than Clear + multiple Appends
            if current_selection != wx.NOT_FOUND and current_selection < len(new_items):
                self.contact_list.SetSelection(current_selection)
            self.contact_list.Thaw()

    async def OnSearch(self, event):
        query = self.search_ctrl.GetValue().strip()
        if not query:
            self.is_searching = False
            self.UpdateContactList()
            return
        
        self.is_searching = True
        self.search_results = await self.api_client.search_users(query)
        self.UpdateContactList()
        self.contact_list.SetFocus()

    def OnSearchText(self, event):
        if not self.search_ctrl.GetValue():
            self.is_searching = False
            self.UpdateContactList()

    async def OnContactSelected(self, event):
        if self._selection_task:
            self._selection_task.cancel()
        
        async def delayed_select():
            await asyncio.sleep(0.25) # 250ms debounce
            await self.DoSelectContact()
            
        self._selection_task = asyncio.create_task(delayed_select())

    async def DoSelectContact(self):
        idx = self.contact_list.GetSelection()
        if idx == wx.NOT_FOUND: return
        
        if self.is_searching:
            if idx >= len(self.search_results): return
            user = self.search_results[idx]
            res = wx.MessageBox(f"Add {user['display_name']} to your contacts?", "Skype™ Reborn", wx.YES_NO)
            if res == wx.YES:
                success, msg = await self.api_client.add_contact(user['username'])
                if success:
                    await self.LoadContacts()
                    self.is_searching = False
                    self.search_ctrl.Clear()
                    self.UpdateContactList()
            return

        if idx >= len(self.contacts): return
        self.selected_contact = self.contacts[idx]
        self.current_conversation_id = self.selected_contact["id"]
        self.chat_header.SetLabel(f"{self.selected_contact['display_name']}")
        
        # Performance: Clear history first to avoid laggy appends
        self.message_history.Clear()
        
        if not self.chat_area.IsShown():
            self.chat_area.Show()
            self.panel.Layout()
            
        await self.LoadMessages()
        # Removed message_input.SetFocus() to prevent stealing focus during navigation

    async def LoadMessages(self):
        messages = await self.api_client.get_messages(self.current_conversation_id)
        # Process messages in one go
        buffer = ""
        for m in messages:
            sender = "Me" if m["sender_id"] == self.user_data["user_id"] else self.selected_contact['display_name']
            buffer += f"{sender}: {m['content']}\n"
        self.message_history.SetValue(buffer)
        self.message_history.SetInsertionPointEnd()

    def append_message(self, sender, content):
        self.message_history.AppendText(f"{sender}: {content}\n")
        self.message_history.SetInsertionPointEnd()

    def OnTyping(self, event):
        if not self.current_conversation_id: return
        async def debounce_typing():
            if not self._is_currently_typing:
                self._is_currently_typing = True
                payload = ChatTypingPayload(conversation_id=self.current_conversation_id, user_id=self.user_data["user_id"], is_typing=True)
                await self.ws_client.send_envelope(Envelope(type=MessageType.CHAT_TYPING, payload=payload.model_dump()))
            await asyncio.sleep(3)
            self._is_currently_typing = False
            payload = ChatTypingPayload(conversation_id=self.current_conversation_id, user_id=self.user_data["user_id"], is_typing=False)
            await self.ws_client.send_envelope(Envelope(type=MessageType.CHAT_TYPING, payload=payload.model_dump()))
        if self.typing_task: self.typing_task.cancel()
        self.typing_task = asyncio.create_task(debounce_typing())

    async def OnGlobalAnswer(self, event):
        if hasattr(self, 'incoming_call_payload'): await self.AnswerCall(self.incoming_call_payload)

    async def OnGlobalHangUp(self, event):
        if self.is_calling: await self.HangUp()

    async def OnSend(self, event):
        content = self.message_input.GetValue().strip()
        if not content or not self.current_conversation_id: return
        payload = ChatMessagePayload(conversation_id=self.current_conversation_id, sender_id=self.user_data["user_id"], content=content)
        envelope = Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump())
        await self.ws_client.send_envelope(envelope)
        self.append_message("Me", content)
        self.message_input.Clear()
        self.play_sound("im_sendmessage.wav")

    async def OnCall(self, event):
        if self.is_calling:
            await self.HangUp()
            return
        if not self.selected_contact: return
        self.play_sound("call_request_sent.wav")
        self.is_calling = True
        self.call_btn.SetLabel("Hang Up")
        self.call_status_text.SetLabel(f"Calling {self.selected_contact['display_name']}...")
        self.call_panel.Show()
        self.chat_area.Layout()
        
        self.active_session_id = uuid4()
        payload = CallSignalPayload(session_id=str(self.active_session_id), target_id=self.selected_contact["id"], sender_id=self.user_data["user_id"])
        await self.ws_client.send_envelope(Envelope(type=MessageType.CALL_INITIATE, payload=payload.model_dump()))
        self.message_history.AppendText(f"Calling {self.selected_contact['display_name']}...\n")
        await self.udp_client.start(self.active_session_id, self.audio_engine.receive_audio, user_id=self.user_data["user_id"])

    async def HangUp(self):
        if self.active_session_id and self.selected_contact:
            payload = CallSignalPayload(session_id=str(self.active_session_id), target_id=self.selected_contact["id"], sender_id=self.user_data["user_id"])
            await self.ws_client.send_envelope(Envelope(type=MessageType.CALL_HANGUP, payload=payload.model_dump()))
        self.stop_call()

    def stop_call(self):
        self.stop_looping_sound()
        self.audio_engine.stop()
        self.udp_client.stop()
        self.is_calling = False
        self.call_btn.SetLabel("Call")
        self.call_panel.Hide()
        self.chat_area.Layout()
        self.message_history.AppendText("Call ended.\n")
        self.play_sound("call_end.wav")
        if hasattr(self, 'incoming_call_payload'): del self.incoming_call_payload

    async def AnswerCall(self, payload):
        self.stop_looping_sound()
        self.play_sound("Call_Answer.wav")
        self.active_session_id = UUID(payload.session_id)
        accept_payload = CallSignalPayload(session_id=payload.session_id, target_id=payload.sender_id, sender_id=self.user_data["user_id"])
        await self.ws_client.send_envelope(Envelope(type=MessageType.CALL_ACCEPT, payload=accept_payload.model_dump()))
        await self.udp_client.start(self.active_session_id, self.audio_engine.receive_audio, user_id=self.user_data["user_id"])
        self.audio_engine.start(self.udp_client.send_audio)
        self.is_calling = True
        if not self.chat_area.IsShown():
            self.chat_area.Show()
        
        self.call_status_text.SetLabel(f"In call with contact")
        self.call_panel.Show()
        self.panel.Layout()
        
        self.call_btn.SetLabel("Hang Up")
        self.message_history.AppendText(f"Call with contact started.\n")

    async def on_ws_message(self, envelope: Envelope):
        if envelope.type == MessageType.CHAT_RECEIVE:
            payload = ChatMessagePayload(**envelope.payload)
            sender_name = self.selected_contact['display_name'] if self.selected_contact else "Friend"
            self.append_message(sender_name, payload.content)
            self.play_sound("im_sendmessage.wav")
            self.RequestUserAttention(wx.USER_ATTENTION_INFO)
        elif envelope.type == MessageType.CHAT_TYPING:
            payload = ChatTypingPayload(**envelope.payload)
            if payload.is_typing: self.typing_status.SetLabel("Typing...")
            else: self.typing_status.SetLabel("")
        elif envelope.type == MessageType.CONTACT_REQUEST:
            self.play_sound("misk_chatrequest.wav")
            await self.LoadContacts()
        elif envelope.type == MessageType.PRESENCE_BROADCAST:
            payload = PresenceUpdatePayload(**envelope.payload)
            # Update local contacts list instead of re-fetching everything
            updated = False
            for c in self.contacts:
                if c["id"] == payload.user_id:
                    c["status"] = payload.status.value
                    updated = True
                    break
            if updated:
                self.TriggerUpdate()
            else:
                # If it's a new contact we don't know about, maybe re-fetch
                await self.LoadContacts()
        elif envelope.type == MessageType.CALL_INITIATE:
            payload = CallSignalPayload(**envelope.payload)
            self.incoming_call_payload = payload
            if self.is_calling: self.play_sound("call_ring_active.wav", loop=True)
            else: self.play_sound("call_ring1.wav", loop=True)
            sender_name = "Someone"
            for c in self.contacts:
                if c["id"] == payload.sender_id: sender_name = c["display_name"]
            self.RequestUserAttention(wx.USER_ATTENTION_ERROR)
            res = wx.MessageBox(f"Skype: {sender_name} is calling. Answer?", "Incoming Call", wx.YES_NO)
            if res == wx.YES: await self.AnswerCall(payload)
            else:
                await self.ws_client.send_envelope(Envelope(type=MessageType.CALL_REJECT, payload=payload.model_dump()))
                self.stop_looping_sound()
        elif envelope.type == MessageType.CALL_CONNECTING: self.play_sound("call_connecting.wav", loop=True)
        elif envelope.type == MessageType.CALL_ACCEPT:
            self.stop_looping_sound()
            self.message_history.AppendText("Call accepted.\n")
            self.call_btn.SetLabel("Hang Up")
            self.audio_engine.start(self.udp_client.send_audio)
        elif envelope.type == MessageType.CALL_REJECT:
            self.message_history.AppendText("Call rejected.\n")
            self.stop_call()
        elif envelope.type == MessageType.CALL_HANGUP:
            self.message_history.AppendText("Peer hung up.\n")
            self.stop_call()