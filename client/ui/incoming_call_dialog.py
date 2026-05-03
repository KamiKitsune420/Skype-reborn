import wx

_BG = wx.Colour(18, 38, 58)
_BTN_GREEN = wx.Colour(16, 124, 16)
_BTN_RED = wx.Colour(196, 49, 75)
_BTN_BLUE = wx.Colour(0, 120, 212)
_BTN_DARK = wx.Colour(40, 70, 100)
_BTN_MUTED = wx.Colour(80, 80, 80)
_WHITE = wx.WHITE
_SUB = wx.Colour(170, 205, 235)


class IncomingCallDialog(wx.Dialog):
    """Incoming call window shown on the receiver's end."""

    def __init__(self, parent, caller_name: str, call_type: str = "Voice"):
        title = f"Skype {call_type} Call from {caller_name}"
        super().__init__(
            parent,
            title=title,
            size=(370, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
            name=title,
        )
        self.SetBackgroundColour(_BG)
        self.mute_on_answer = False
        self._build(caller_name, call_type)
        self.Centre()
        # Give focus to Answer so screen readers announce it immediately
        wx.CallAfter(self._answer_btn.SetFocus)

    def _build(self, caller_name: str, call_type: str):
        sz = wx.BoxSizer(wx.VERTICAL)
        sz.AddSpacer(24)

        def _lbl(text, pt=10, bold=False, colour=_SUB):
            s = wx.StaticText(self, label=text, style=wx.ALIGN_CENTER)
            f = s.GetFont()
            f.SetPointSize(pt)
            if bold:
                f.SetWeight(wx.FONTWEIGHT_BOLD)
            s.SetFont(f)
            s.SetForegroundColour(colour)
            s.SetBackgroundColour(_BG)
            return s

        sz.Add(_lbl(f"Skype {call_type} Call"), 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        sz.Add(_lbl(caller_name, pt=20, bold=True, colour=_WHITE), 0, wx.ALIGN_CENTER | wx.BOTTOM, 6)
        sz.Add(
            _lbl(f"Incoming {call_type.lower()} call...", pt=9),
            0, wx.ALIGN_CENTER | wx.BOTTOM, 28,
        )

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._answer_btn = wx.Button(self, label="Answer", size=(130, 48))
        self._answer_btn.SetBackgroundColour(_BTN_GREEN)
        self._answer_btn.SetForegroundColour(_WHITE)
        self._decline_btn = wx.Button(self, label="Decline", size=(130, 48))
        self._decline_btn.SetBackgroundColour(_BTN_RED)
        self._decline_btn.SetForegroundColour(_WHITE)
        btn_row.Add(self._answer_btn, 0, wx.RIGHT, 12)
        btn_row.Add(self._decline_btn, 0)
        sz.Add(btn_row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 24)

        sz.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        def _ctrl(label, colour=_BTN_DARK):
            btn = wx.Button(self, label=label)
            btn.SetMinSize((-1, 40))
            btn.SetBackgroundColour(colour)
            btn.SetForegroundColour(_WHITE)
            sz.Add(btn, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            return btn

        self._mute_btn  = _ctrl("Mute Microphone", _BTN_BLUE)
        self._camera_btn = _ctrl("Turn on Camera")
        self._addp_btn  = _ctrl("Add Participant")
        self._min_btn   = _ctrl("Minimize")

        self.SetSizer(sz)

        self._answer_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_YES))
        self._decline_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_NO))
        self._mute_btn.Bind(wx.EVT_BUTTON, self._on_mute)
        self._camera_btn.Bind(
            wx.EVT_BUTTON,
            lambda e: wx.MessageBox(
                "Video calls are not yet supported.",
                "Coming Soon", wx.OK | wx.ICON_INFORMATION, self,
            ),
        )
        self._addp_btn.Bind(
            wx.EVT_BUTTON,
            lambda e: wx.MessageBox(
                "Group calls are not yet supported.",
                "Coming Soon", wx.OK | wx.ICON_INFORMATION, self,
            ),
        )
        self._min_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        self.Bind(wx.EVT_CLOSE, lambda e: self.EndModal(wx.ID_NO))
        self.SetDefaultItem(self._answer_btn)

    def _on_mute(self, event):
        self.mute_on_answer = not self.mute_on_answer
        if self.mute_on_answer:
            self._mute_btn.SetLabel("Unmute Microphone")
            self._mute_btn.SetBackgroundColour(_BTN_MUTED)
        else:
            self._mute_btn.SetLabel("Mute Microphone")
            self._mute_btn.SetBackgroundColour(_BTN_BLUE)
        self._mute_btn.Refresh()
