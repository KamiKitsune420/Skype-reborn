import threading
import wx
import structlog

logger = structlog.get_logger()

_BLUE = wx.Colour(0, 120, 212)


class FindPeopleDialog(wx.Dialog):
    """Search for users and add them as contacts."""

    def __init__(self, parent, on_search, on_add):
        super().__init__(
            parent,
            title="Find People",
            size=(440, 460),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name="Find People Dialog",
        )
        self.on_search = on_search
        self.on_add = on_add
        self._results = []
        self._build_ui()
        self.Centre()
        self.search_ctrl.SetFocus()

    def _build_ui(self):
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.WHITE)
        root = wx.BoxSizer(wx.VERTICAL)

        # ── Header ───────────────────────────────────────────────────
        hdr = wx.Panel(panel)
        hdr.SetBackgroundColour(_BLUE)
        hdr_sz = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(hdr, label="Find People")
        f = title.GetFont()
        f.SetPointSize(13)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(f)
        title.SetForegroundColour(wx.WHITE)
        hdr_sz.Add(title, 0, wx.ALL, 14)
        hdr.SetSizer(hdr_sz)
        root.Add(hdr, 0, wx.EXPAND)

        # ── Search row ───────────────────────────────────────────────
        root.Add(wx.StaticText(panel, label="Search by Skype name or display name:"),
                 0, wx.LEFT | wx.TOP, 16)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        self.search_ctrl = wx.TextCtrl(
            panel, style=wx.TE_PROCESS_ENTER, name="Search Input"
        )
        self.search_ctrl.SetHint("Type a name…")
        self.search_ctrl.SetMinSize((-1, 32))
        self.search_btn = wx.Button(panel, label="Search", name="Search Button")
        self.search_btn.SetDefault()
        search_row.Add(self.search_ctrl, 1, wx.ALL, 4)
        search_row.Add(self.search_btn, 0, wx.ALL, 4)
        root.Add(search_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)

        # ── Status label ─────────────────────────────────────────────
        self.status_lbl = wx.StaticText(panel, label="", style=wx.ALIGN_CENTER)
        self.status_lbl.SetForegroundColour(wx.Colour(96, 94, 92))
        f2 = self.status_lbl.GetFont()
        f2.SetPointSize(9)
        self.status_lbl.SetFont(f2)
        root.Add(self.status_lbl, 0, wx.ALIGN_CENTER | wx.TOP, 8)

        # ── Results list ─────────────────────────────────────────────
        self.results_list = wx.ListBox(
            panel, style=wx.LB_SINGLE | wx.BORDER_SIMPLE, name="Search Results"
        )
        self.results_list.SetMinSize((-1, 180))
        root.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 12)

        # ── Bottom buttons ────────────────────────────────────────────
        root.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.AddStretchSpacer()
        self.add_btn   = wx.Button(panel, label="Add to Contacts")
        self.close_btn = wx.Button(panel, wx.ID_CANCEL, "Close")
        self.add_btn.Disable()
        btn_row.Add(self.add_btn, 0, wx.ALL, 8)
        btn_row.Add(self.close_btn, 0, wx.RIGHT | wx.TOP | wx.BOTTOM, 8)
        root.Add(btn_row, 0, wx.EXPAND)

        panel.SetSizer(root)

        self.search_btn.Bind(wx.EVT_BUTTON, self.OnSearch)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.OnSearch)
        self.add_btn.Bind(wx.EVT_BUTTON, self.OnAdd)
        self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self.OnAdd)
        self.results_list.Bind(wx.EVT_LISTBOX, self._on_result_selected)

    def _on_result_selected(self, event):
        self.add_btn.Enable(self.results_list.GetSelection() != wx.NOT_FOUND)

    def OnSearch(self, event):
        query = self.search_ctrl.GetValue().strip()
        if not query:
            return
        self.search_btn.Disable()
        self.search_btn.SetLabel("Searching…")
        self.add_btn.Disable()
        self.results_list.Clear()
        self._results = []
        self.status_lbl.SetLabel("Searching…")
        threading.Thread(target=self._bg_search, args=(query,), daemon=True).start()

    def _bg_search(self, query: str):
        try:
            results = self.on_search(query)
        except Exception as e:
            results = []
            wx.CallAfter(self.status_lbl.SetLabel, f"Search failed: {e}")
        wx.CallAfter(self._on_search_done, results)

    def _on_search_done(self, results):
        self.search_btn.Enable()
        self.search_btn.SetLabel("Search")
        self._results = results
        self.results_list.Clear()
        if not results:
            self.status_lbl.SetLabel("No results found.")
            self.add_btn.Disable()
        else:
            self.status_lbl.SetLabel(f"{len(results)} result(s) found. Double-click to add.")
            for r in results:
                tag = "  [Bot]" if r.get("is_bot") else ""
                self.results_list.Append(
                    f"{r['display_name']}{tag}  ({r['username']})", r
                )
            self.results_list.SetFocus()
            self.add_btn.Disable()

    def OnAdd(self, event):
        selection = self.results_list.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        user_data = self.results_list.GetClientData(selection)
        self.on_add(user_data)
        self.EndModal(wx.ID_OK)
