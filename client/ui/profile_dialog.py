"""Profile view/edit dialog."""
import os
import threading
import wx
import structlog

logger = structlog.get_logger()

_BLUE = wx.Colour(0, 120, 212)
_TEXT = wx.Colour(32, 31, 30)
_GRAY = wx.Colour(96, 94, 92)

_AVATAR_DIR = os.path.join("assets", "avatars")


class ProfileDialog(wx.Dialog):
    """View and edit the signed-in user's profile."""

    def __init__(self, parent, api_client, user_data: dict):
        super().__init__(
            parent,
            title="My Profile",
            size=(480, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name="Profile Dialog",
        )
        self.api_client  = api_client
        self.user_data   = user_data
        self._avatar_bmp = None
        self._build_ui()
        self.Centre()
        threading.Thread(target=self._load_profile, daemon=True).start()

    # ── Build ─────────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.WHITE)
        root = wx.BoxSizer(wx.VERTICAL)

        # ── Blue header ──────────────────────────────────────────────
        hdr = wx.Panel(panel)
        hdr.SetBackgroundColour(_BLUE)
        hdr_sz = wx.BoxSizer(wx.HORIZONTAL)

        # Avatar
        avatar_path = self._local_avatar_path()
        if os.path.exists(avatar_path):
            img = wx.Image(avatar_path, wx.BITMAP_TYPE_ANY).Scale(
                64, 64, wx.IMAGE_QUALITY_HIGH
            )
        else:
            anon = os.path.join("assets", "images", "profile_anonymous.png")
            if os.path.exists(anon):
                img = wx.Image(anon, wx.BITMAP_TYPE_ANY).Scale(
                    64, 64, wx.IMAGE_QUALITY_HIGH
                )
            else:
                img = wx.Image(64, 64)
        self.avatar_bmp = wx.StaticBitmap(hdr, bitmap=wx.Bitmap(img), name="Profile Picture")
        hdr_sz.Add(self.avatar_bmp, 0, wx.ALL, 12)

        name_col = wx.BoxSizer(wx.VERTICAL)
        self.hdr_name = wx.StaticText(hdr, label=self.user_data.get("username", ""))
        f = self.hdr_name.GetFont()
        f.SetPointSize(13)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.hdr_name.SetFont(f)
        self.hdr_name.SetForegroundColour(wx.WHITE)
        name_col.Add(self.hdr_name, 0, wx.TOP, 8)

        self.hdr_mood = wx.StaticText(hdr, label="")
        mf = self.hdr_mood.GetFont()
        mf.SetPointSize(9)
        mf.SetStyle(wx.FONTSTYLE_ITALIC)
        self.hdr_mood.SetFont(mf)
        self.hdr_mood.SetForegroundColour(wx.Colour(200, 230, 255))
        name_col.Add(self.hdr_mood, 0, wx.TOP, 4)

        hdr_sz.Add(name_col, 1, wx.ALIGN_CENTER_VERTICAL)
        hdr.SetSizer(hdr_sz)
        hdr.SetMinSize((-1, 90))
        root.Add(hdr, 0, wx.EXPAND)

        # ── Photo buttons ────────────────────────────────────────────
        photo_row = wx.BoxSizer(wx.HORIZONTAL)
        sel_btn  = wx.Button(panel, label="Select Photo from File")
        cam_btn  = wx.Button(panel, label="Take Photo with Camera")
        photo_row.Add(sel_btn, 1, wx.ALL, 6)
        photo_row.Add(cam_btn, 1, wx.ALL, 6)
        root.Add(photo_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ── Edit fields ──────────────────────────────────────────────
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
        grid.AddGrowableCol(1, 1)

        def _row(label, name, hint=""):
            lbl  = wx.StaticText(panel, label=label)
            ctrl = wx.TextCtrl(panel, name=name)
            if hint:
                ctrl.SetHint(hint)
            grid.Add(lbl,  0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)
            return ctrl

        self.f_display  = _row("Display name:",  "DisplayName")
        self.f_mood     = _row("Mood message:",   "Mood",     "What's on your mind?")
        self.f_country  = _row("Country:",        "Country")
        self.f_hometown = _row("Hometown:",       "Hometown")
        self.f_birthday = _row("Birthday:",       "Birthday", "e.g. April 26, 1990")

        # Read-only fields
        self.f_username = _row("Skype Name:",     "Username")
        self.f_email    = _row("Email:",          "Email")
        self.f_username.SetEditable(False)
        self.f_email.SetEditable(False)

        root.Add(grid, 0, wx.EXPAND | wx.ALL, 16)

        # ── Buttons ──────────────────────────────────────────────────
        root.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.AddStretchSpacer()
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        save_btn   = wx.Button(panel, wx.ID_OK, "Save")
        save_btn.SetDefault()
        btn_row.Add(cancel_btn, 0, wx.ALL, 8)
        btn_row.Add(save_btn,   0, wx.RIGHT | wx.TOP | wx.BOTTOM, 8)
        root.Add(btn_row, 0, wx.EXPAND)

        panel.SetSizer(root)

        sel_btn.Bind(wx.EVT_BUTTON, self._on_select_photo)
        cam_btn.Bind(wx.EVT_BUTTON, self._on_camera)
        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

    # ── Load profile from server ──────────────────────────────────────

    def _load_profile(self):
        data = self.api_client.get_profile()
        wx.CallAfter(self._populate, data)

    def _populate(self, data: dict):
        self.f_display.SetValue(data.get("display_name", ""))
        self.f_mood.SetValue(data.get("mood_message", ""))
        self.f_country.SetValue(data.get("country", ""))
        self.f_hometown.SetValue(data.get("hometown", ""))
        self.f_birthday.SetValue(data.get("birthday", ""))
        self.f_username.SetValue(data.get("username", self.user_data.get("username", "")))
        self.f_email.SetValue(data.get("email", ""))
        mood = data.get("mood_message", "")
        self.hdr_mood.SetLabel(mood if mood else "No mood set")

    # ── Photo ─────────────────────────────────────────────────────────

    def _local_avatar_path(self) -> str:
        username = self.user_data.get("username", "user")
        return os.path.join(_AVATAR_DIR, f"{username}.png")

    def _on_select_photo(self, event):
        with wx.FileDialog(
            self, "Select profile photo",
            wildcard="Images (*.png;*.jpg;*.jpeg;*.bmp)|*.png;*.jpg;*.jpeg;*.bmp",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            path = dlg.GetPath()

        os.makedirs(_AVATAR_DIR, exist_ok=True)
        img = wx.Image(path, wx.BITMAP_TYPE_ANY)
        img = img.Scale(64, 64, wx.IMAGE_QUALITY_HIGH)
        dest = self._local_avatar_path()
        img.SaveFile(dest, wx.BITMAP_TYPE_PNG)
        self.avatar_bmp.SetBitmap(wx.Bitmap(img))
        wx.MessageBox("Photo updated. It will appear next time you open the app.",
                      "Photo Updated", wx.OK | wx.ICON_INFORMATION, self)

    def _on_camera(self, event):
        wx.MessageBox(
            "Camera capture is not yet supported in this version.\n"
            "Use 'Select Photo from File' to choose a profile picture.",
            "Camera Not Available", wx.OK | wx.ICON_INFORMATION, self,
        )

    # ── Save ──────────────────────────────────────────────────────────

    def _on_save(self, event):
        threading.Thread(target=self._do_save, daemon=True).start()

    def _do_save(self):
        ok = self.api_client.update_profile(
            display_name=self.f_display.GetValue().strip(),
            mood=self.f_mood.GetValue().strip(),
            country=self.f_country.GetValue().strip(),
            hometown=self.f_hometown.GetValue().strip(),
            birthday=self.f_birthday.GetValue().strip(),
        )
        wx.CallAfter(self._on_save_done, ok)

    def _on_save_done(self, ok: bool):
        if ok:
            wx.MessageBox("Profile saved successfully.",
                          "Saved", wx.OK | wx.ICON_INFORMATION, self)
            self.EndModal(wx.ID_OK)
        else:
            wx.MessageBox("Failed to save profile. Please try again.",
                          "Error", wx.OK | wx.ICON_ERROR, self)
