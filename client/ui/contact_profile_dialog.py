import datetime
import os
import wx


_BLUE = wx.Colour(0, 120, 212)
_TEXT = wx.Colour(32, 31, 30)
_GRAY = wx.Colour(96, 94, 92)
_CARD = wx.Colour(245, 249, 253)
_ONLINE = wx.Colour(16, 124, 16)
_OFFLINE = wx.Colour(161, 70, 70)


def _format_last_seen(raw: str | None) -> str:
    if not raw:
        return "Unknown"
    try:
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt_local = dt.astimezone()
        return dt_local.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")
    except Exception:
        return "Unknown"


def _read_only_value(parent: wx.Window, value: str) -> wx.TextCtrl:
    ctrl = wx.TextCtrl(parent, value=value, style=wx.TE_READONLY | wx.BORDER_NONE)
    ctrl.SetBackgroundColour(_CARD)
    ctrl.SetForegroundColour(_TEXT)
    return ctrl


class ContactProfileDialog(wx.Dialog):
    """Read-only contact profile dialog with structured layout."""

    def __init__(self, parent: wx.Window, contact: dict):
        super().__init__(
            parent,
            title=f"{contact.get('display_name', 'Contact')} Profile",
            size=(480, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name="Contact Profile Dialog",
        )
        self.contact = contact
        self._build_ui()
        self.CentreOnParent()

    def _build_ui(self):
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.WHITE)
        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(self._build_header(panel), 0, wx.EXPAND)
        root.Add(self._build_body(panel), 1, wx.EXPAND | wx.ALL, 14)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.AddStretchSpacer()
        close_btn = wx.Button(panel, wx.ID_OK, "Close")
        close_btn.SetDefault()
        btn_row.Add(close_btn, 0, wx.ALL, 6)
        root.Add(btn_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(root)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

    def _build_header(self, parent: wx.Window) -> wx.Panel:
        hdr = wx.Panel(parent)
        hdr.SetBackgroundColour(_BLUE)
        sz = wx.BoxSizer(wx.HORIZONTAL)

        avatar_bmp = wx.StaticBitmap(hdr, bitmap=self._load_avatar_bitmap(72))
        sz.Add(avatar_bmp, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 12)

        name_col = wx.BoxSizer(wx.VERTICAL)
        name = self.contact.get("display_name", "Contact")
        username = self.contact.get("username", "")
        name_lbl = wx.StaticText(hdr, label=name)
        nf = name_lbl.GetFont()
        nf.SetPointSize(14)
        nf.SetWeight(wx.FONTWEIGHT_BOLD)
        name_lbl.SetFont(nf)
        name_lbl.SetForegroundColour(wx.WHITE)
        name_col.Add(name_lbl, 0, wx.TOP, 4)

        if username:
            username_lbl = wx.StaticText(hdr, label=f"Skype Name: {username}")
            uf = username_lbl.GetFont()
            uf.SetPointSize(9)
            username_lbl.SetFont(uf)
            username_lbl.SetForegroundColour(wx.Colour(214, 236, 255))
            name_col.Add(username_lbl, 0, wx.TOP, 4)

        status = str(self.contact.get("status", "OFFLINE")).upper()
        status_text = "Online" if status == "ONLINE" else status.capitalize()
        status_lbl = wx.StaticText(hdr, label=status_text)
        sf = status_lbl.GetFont()
        sf.SetPointSize(9)
        sf.SetWeight(wx.FONTWEIGHT_BOLD)
        status_lbl.SetFont(sf)
        status_lbl.SetForegroundColour(_ONLINE if status == "ONLINE" else _OFFLINE)
        name_col.Add(status_lbl, 0, wx.TOP, 6)

        sz.Add(name_col, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        hdr.SetSizer(sz)
        hdr.SetMinSize((-1, 112))
        return hdr

    def _build_body(self, parent: wx.Window) -> wx.Panel:
        body = wx.Panel(parent)
        body.SetBackgroundColour(wx.WHITE)
        body_sizer = wx.BoxSizer(wx.VERTICAL)

        card = wx.Panel(body)
        card.SetBackgroundColour(_CARD)
        card_sz = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=2, hgap=12, vgap=10)
        grid.AddGrowableCol(1, 1)

        def add_field(label: str, value: str):
            lbl = wx.StaticText(card, label=label)
            lf = lbl.GetFont()
            lf.SetPointSize(9)
            lf.SetWeight(wx.FONTWEIGHT_BOLD)
            lbl.SetFont(lf)
            lbl.SetForegroundColour(_GRAY)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
            grid.Add(_read_only_value(card, value), 1, wx.EXPAND | wx.RIGHT, 4)

        add_field("Display Name", self.contact.get("display_name", ""))
        add_field("Skype Name", self.contact.get("username", ""))
        add_field("Status", str(self.contact.get("status", "OFFLINE")).capitalize())

        status = str(self.contact.get("status", "OFFLINE")).upper()
        last_seen = "Online now" if status == "ONLINE" else _format_last_seen(self.contact.get("last_seen"))
        add_field("Last Seen", last_seen)

        mood = self.contact.get("mood_message", "").strip() or "No mood message"
        mood_lbl = wx.StaticText(card, label="Mood Message")
        mf = mood_lbl.GetFont()
        mf.SetPointSize(9)
        mf.SetWeight(wx.FONTWEIGHT_BOLD)
        mood_lbl.SetFont(mf)
        mood_lbl.SetForegroundColour(_GRAY)
        card_sz.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        card_sz.Add(mood_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        mood_txt = wx.StaticText(card, label=mood)
        mood_txt.SetForegroundColour(_TEXT)
        mood_txt.Wrap(400)
        card_sz.Add(mood_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 10)

        card.SetSizer(card_sz)
        body_sizer.Add(card, 1, wx.EXPAND)
        body.SetSizer(body_sizer)
        return body

    def _load_avatar_bitmap(self, size: int) -> wx.Bitmap:
        username = self.contact.get("username", "")
        local_avatar = os.path.join("assets", "avatars", f"{username}.png")
        fallback = os.path.join("assets", "images", "profile_unknown.png")
        source = local_avatar if os.path.exists(local_avatar) else fallback
        if os.path.exists(source):
            img = wx.Image(source, wx.BITMAP_TYPE_ANY).Scale(size, size, wx.IMAGE_QUALITY_HIGH)
            return wx.Bitmap(img)
        return wx.ArtProvider.GetBitmap(wx.ART_MISSING_IMAGE, wx.ART_OTHER, (size, size))
