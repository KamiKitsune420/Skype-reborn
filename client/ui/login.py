import wx
import wx.adv
import os
import threading
import structlog
from ..network.api_client import APIClient

logger = structlog.get_logger()


class LoginFrame(wx.Frame):
    def __init__(self, api_client: APIClient, on_login_success):
        super().__init__(
            None,
            title="Skype™ Reborn — Login",
            size=(400, 650),
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX),
            name="Skype Login Window",
        )
        self.api_client = api_client
        self._on_login_success = on_login_success
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        self.panel = wx.Panel(self, name="Login Panel")
        root = wx.BoxSizer(wx.VERTICAL)

        # Logo
        header_path = os.path.join("assets", "images", "skype_header.png")
        if os.path.exists(header_path):
            img = wx.Image(header_path, wx.BITMAP_TYPE_ANY)
            w, h = img.GetSize()
            new_h = int(h * (400 / w))
            img = img.Scale(400, new_h, wx.IMAGE_QUALITY_HIGH)
            root.Add(wx.StaticBitmap(self.panel, -1, wx.Bitmap(img), name="Skype Logo"),
                     0, wx.EXPAND | wx.BOTTOM, 20)

        # ── Login view ───────────────────────────────────────────────
        self.login_view = wx.Panel(self.panel)
        lv = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(2, 2, 10, 25)
        grid.AddGrowableCol(1, 1)

        self.user_label = wx.StaticText(self.login_view, label="&Skype Name", name="Skype Name Label")
        self.user_ctrl = wx.TextCtrl(self.login_view, name="Skype Name Input")
        self.pass_label = wx.StaticText(self.login_view, label="&Password", name="Password Label")
        self.pass_ctrl = wx.TextCtrl(self.login_view, style=wx.TE_PASSWORD, name="Password Input")

        for widget in (self.user_label, self.user_ctrl, self.pass_label, self.pass_ctrl):
            grid.Add(widget, 0 if isinstance(widget, wx.StaticText) else 1,
                     wx.ALIGN_CENTER_VERTICAL if isinstance(widget, wx.StaticText) else wx.EXPAND)

        lv.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 30)

        self.remember_cb = wx.CheckBox(self.login_view, label="&Remember me")
        lv.Add(self.remember_cb, 0, wx.LEFT | wx.BOTTOM, 30)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.to_reg_btn = wx.Button(self.login_view, label="Create &account", size=(130, 35))
        self.login_btn = wx.Button(self.login_view, label="&Sign in", size=(100, 35))
        self.login_btn.SetDefault()
        btn_row.Add(self.to_reg_btn, 0, wx.RIGHT, 15)
        btn_row.Add(self.login_btn)
        lv.Add(btn_row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 25)

        self.login_view.SetSizer(lv)
        root.Add(self.login_view, 1, wx.EXPAND)

        # ── Register view ────────────────────────────────────────────
        self.register_view = wx.Panel(self.panel, name="Registration View")
        rv = wx.BoxSizer(wx.VERTICAL)

        reg_grid = wx.FlexGridSizer(5, 2, 10, 25)
        reg_grid.AddGrowableCol(1, 1)

        fields = [
            ("&Skype Name",  "Reg Skype Name",   False),
            ("&Password",    "Reg Password",      True),
            ("&Email",       "Reg Email",         False),
            ("&First Name",  "Reg First Name",    False),
            ("&Last Name",   "Reg Last Name",     False),
        ]
        self._reg_ctrls = []
        for label, name, is_pass in fields:
            lbl = wx.StaticText(self.register_view, label=label)
            ctrl = wx.TextCtrl(
                self.register_view,
                style=wx.TE_PASSWORD if is_pass else 0,
                name=name,
            )
            self._reg_ctrls.append(ctrl)
            reg_grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            reg_grid.Add(ctrl, 1, wx.EXPAND)

        rv.Add(reg_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 30)

        reg_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.back_btn = wx.Button(self.register_view, label="&Back", size=(100, 35),
                                   name="Back to Login Button")
        self.do_reg_btn = wx.Button(self.register_view, label="&Register", size=(100, 35),
                                     name="Register Action Button")
        reg_btn_row.Add(self.back_btn, 0, wx.RIGHT, 15)
        reg_btn_row.Add(self.do_reg_btn)
        rv.Add(reg_btn_row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 25)

        self.register_view.SetSizer(rv)
        root.Add(self.register_view, 1, wx.EXPAND)
        self.register_view.Hide()

        # Status line
        self.status_text = wx.StaticText(self.panel, label="", style=wx.ALIGN_CENTER)
        root.Add(self.status_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.panel.SetSizer(root)

        # Bindings (all sync — threads handle network work)
        self.login_btn.Bind(wx.EVT_BUTTON, self.OnLogin)
        self.do_reg_btn.Bind(wx.EVT_BUTTON, self.OnRegister)
        self.to_reg_btn.Bind(wx.EVT_BUTTON, lambda e: self._show_view("register"))
        self.back_btn.Bind(wx.EVT_BUTTON, lambda e: self._show_view("login"))

    def _show_view(self, which: str):
        self.login_view.Show(which == "login")
        self.register_view.Show(which == "register")
        self.status_text.SetLabel("")
        self.panel.Layout()

    # ── Login ────────────────────────────────────────────────────────

    def OnLogin(self, event):
        username = self.user_ctrl.GetValue().strip()
        password = self.pass_ctrl.GetValue().strip()
        if not username or not password:
            self.status_text.SetLabel("Enter Skype Name and password.")
            return
        self.status_text.SetLabel("Signing in…")
        self.login_btn.Disable()
        threading.Thread(
            target=self._do_login, args=(username, password), daemon=True
        ).start()

    def _do_login(self, username: str, password: str):
        success, res = self.api_client.login(username, password)
        wx.CallAfter(self._on_login_done, success, res)

    def _on_login_done(self, success: bool, res):
        if success:
            self.status_text.SetLabel("Success!")
            sound_path = os.path.join("assets", "sounds", "misk_signin.wav")
            if os.path.exists(sound_path):
                s = wx.adv.Sound(sound_path)
                if s.IsOk():
                    s.Play(wx.adv.SOUND_ASYNC)
            self._on_login_success(res)
        else:
            self.status_text.SetLabel(f"Sign in failed: {res}")
            self.login_btn.Enable()

    # ── Register ─────────────────────────────────────────────────────

    def OnRegister(self, event):
        keys = ["username", "password", "email", "first_name", "last_name"]
        data = {k: c.GetValue().strip() for k, c in zip(keys, self._reg_ctrls)}
        if any(not v for v in data.values()):
            self.status_text.SetLabel("All fields are required.")
            return
        self.status_text.SetLabel("Creating account…")
        self.do_reg_btn.Disable()
        threading.Thread(target=self._do_register, args=(data,), daemon=True).start()

    def _do_register(self, data: dict):
        success, msg = self.api_client.register(data)
        wx.CallAfter(self._on_register_done, success, msg)

    def _on_register_done(self, success: bool, msg: str):
        self.do_reg_btn.Enable()
        if success:
            self.status_text.SetLabel("Account created. You can now sign in.")
            self._show_view("login")
        else:
            self.status_text.SetLabel(f"Failed: {msg}")
