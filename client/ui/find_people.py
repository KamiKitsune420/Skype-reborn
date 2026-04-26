import wx
import structlog

logger = structlog.get_logger()

class FindPeopleDialog(wx.Dialog):
    def __init__(self, parent, on_search, on_add):
        super().__init__(parent, title="Find People", size=(400, 500))
        self.on_search = on_search
        self.on_add = on_add
        
        self.panel = wx.Panel(self)
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Search area
        self.search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.search_label = wx.StaticText(self.panel, label="&Skype Name or Email:")
        self.search_ctrl = wx.TextCtrl(self.panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetName("Search for Skype Name or Email")
        
        self.search_btn = wx.Button(self.panel, label="&Search")
        self.search_btn.SetDefault()
        
        self.search_sizer.Add(self.search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.search_sizer.Add(self.search_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        self.search_sizer.Add(self.search_btn, 0, wx.ALL, 5)
        
        self.sizer.Add(self.search_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Results area (hidden initially)
        self.results_list = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.results_list.SetName("Search Results List")
        self.results_list.Hide()
        self.sizer.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 10)
        
        self.no_results_text = wx.StaticText(self.panel, label="No results found.", style=wx.ALIGN_CENTER)
        self.no_results_text.Hide()
        self.sizer.Add(self.no_results_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        # Action buttons
        self.action_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_btn = wx.Button(self.panel, label="&Add to Contacts")
        self.add_btn.Hide()
        self.cancel_btn = wx.Button(self.panel, label="&Cancel")
        
        self.action_sizer.Add(self.add_btn, 0, wx.ALL, 5)
        self.action_sizer.Add(self.cancel_btn, 0, wx.ALL, 5)
        self.sizer.Add(self.action_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        self.panel.SetSizer(self.sizer)
        
        # Bindings
        self.search_btn.Bind(wx.EVT_BUTTON, self.OnSearch)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.OnSearch)
        self.add_btn.Bind(wx.EVT_BUTTON, self.OnAdd)
        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self.OnAdd)

    def OnSearch(self, event):
        query = self.search_ctrl.GetValue().strip()
        if not query:
            return
            
        # Hide search UI as requested
        self.search_label.Hide()
        self.search_ctrl.Hide()
        self.search_btn.Hide()
        
        # In a real app, this would be a background thread
        results = self.on_search(query)
        self.DisplayResults(results)
        
    def DisplayResults(self, results):
        self.results_list.Clear()
        if not results:
            self.results_list.Hide()
            self.no_results_text.Show()
            self.add_btn.Hide()
        else:
            self.no_results_text.Hide()
            for r in results:
                self.results_list.Append(f"{r['display_name']} ({r['username']})", r)
            self.results_list.Show()
            self.add_btn.Show()
            self.results_list.SetFocus()
        
        self.panel.Layout()

    def OnAdd(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            user_data = self.results_list.GetClientData(selection)
            self.on_add(user_data)
            self.EndModal(wx.ID_OK)
