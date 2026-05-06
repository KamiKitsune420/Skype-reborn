import os
import threading
import wx
import structlog
from ..services.auth import AuthService
from ..audio.sounds import SoundPlayer
from ..services.settings_store import load_settings, save_settings

logger = structlog.get_logger()

# Skype 7-inspired palette
_BLUE     = wx.Colour(0, 120, 212)
_BG       = wx.Colour(255, 255, 255)
_TEXT     = wx.Colour(32, 31, 30)
_GRAY     = wx.Colour(96, 94, 92)
_BORDER   = wx.Colour(200, 198, 196)
_ERROR    = wx.Colour(168, 0, 0)
_SUCCESS  = wx.Colour(16, 124, 16)


def _bold(ctrl):
    f = ctrl.GetFont()
    f.SetWeight(wx.FONTWEIGHT_BOLD)
    ctrl.SetFont(f)


class LoginFrame(wx.Frame):
    def __init__(self, auth_service: AuthService, on_login_success):
        super().__init__(
            None,
            title="Skype™ Reborn",
            size=(420, 580),
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX),
            name="Login Window",
        )
        self.auth_service = auth_service
        self._on_login_success = on_login_success
        self.SetBackgroundColour(_BG)
        self._build_ui()
        self.Centre()
        self._prefill_saved_credentials()

    # ── Layout ───────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self, name="Login Panel")
        panel.SetBackgroundColour(_BG)
        root = wx.BoxSizer(wx.VERTICAL)

        # Logo
        logo_path = os.path.join("assets", "images", "skype_header.png")
        if os.path.exists(logo_path):
            img = wx.Image(logo_path, wx.BITMAP_TYPE_ANY)
            w, h = img.GetSize()
            new_h = int(h * (340 / w))
            img = img.Scale(340, new_h, wx.IMAGE_QUALITY_HIGH)
            root.Add(
                wx.StaticBitmap(panel, bitmap=wx.Bitmap(img), name="Logo"),
                0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 16,
            )
        else:
            title = wx.StaticText(panel, label="Skype™ Reborn", style=wx.ALIGN_CENTER)
            f = title.GetFont()
            f.SetPointSize(20)
            f.SetWeight(wx.FONTWEIGHT_BOLD)
            title.SetFont(f)
            title.SetForegroundColour(_BLUE)
            root.Add(title, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 24)

        # Page switcher
        self._book = wx.Simplebook(panel)
        self._book.SetBackgroundColour(_BG)
        self._build_login_page()
        self._build_register_page()
        root.Add(self._book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 36)

        # Status text
        self.status_text = wx.StaticText(
            panel, label="", style=wx.ALIGN_CENTER, name="Status Text"
        )
        f2 = self.status_text.GetFont()
        f2.SetPointSize(9)
        self.status_text.SetFont(f2)
        self.status_text.SetForegroundColour(_ERROR)
        root.Add(self.status_text, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(root)

    def _field(self, parent, label: str, name: str, password: bool = False):
        """Returns (label_widget, text_ctrl) stacked vertically — caller adds both."""
        lbl = wx.StaticText(parent, label=label)
        lbl.SetForegroundColour(_TEXT)
        f = lbl.GetFont()
        f.SetPointSize(9)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        lbl.SetFont(f)
        style = wx.TE_PROCESS_ENTER | (wx.TE_PASSWORD if password else 0)
        ctrl = wx.TextCtrl(parent, style=style, name=name)
        ctrl.SetMinSize((-1, 32))
        return lbl, ctrl

    def _build_login_page(self):
        page = wx.Panel(self._book, name="Login Page")
        page.SetBackgroundColour(_BG)
        sz = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(page, label="Sign in to Skype™ Reborn")
        f = hdr.GetFont()
        f.SetPointSize(13)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        hdr.SetFont(f)
        hdr.SetForegroundColour(_TEXT)
        sz.Add(hdr, 0, wx.BOTTOM, 6)

        # Show which server the client is pointed at so it's obvious
        # whether you're on localhost or the remote server.
        import os as _os
        _server = _os.environ.get("SKYPE_SERVER_URL", "http://random-gaming.com:9433")
        _is_local = "127.0.0.1" in _server or "localhost" in _server
        server_lbl = wx.StaticText(
            page,
            label=f"{'🖥 LOCAL — ' if _is_local else '🌐 '}{_server}",
            name="Server Label",
        )
        sf = server_lbl.GetFont()
        sf.SetPointSize(8)
        server_lbl.SetFont(sf)
        server_lbl.SetForegroundColour(wx.Colour(16, 124, 16) if _is_local else _GRAY)
        sz.Add(server_lbl, 0, wx.BOTTOM, 14)

        user_lbl, self.user_ctrl = self._field(page, "Skype Name", "Username")
        sz.Add(user_lbl, 0, wx.BOTTOM, 4)
        sz.Add(self.user_ctrl, 0, wx.EXPAND | wx.BOTTOM, 12)

        pass_lbl, self.pass_ctrl = self._field(page, "Password", "Password", password=True)
        sz.Add(pass_lbl, 0, wx.BOTTOM, 4)
        sz.Add(self.pass_ctrl, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.remember_cb = wx.CheckBox(page, label="Remember me")
        sz.Add(self.remember_cb, 0, wx.BOTTOM, 18)

        # Primary button — Sign In
        self.login_btn = wx.Button(page, label="Sign In", name="Sign In")
        self.login_btn.SetDefault()
        self.login_btn.SetBackgroundColour(_BLUE)
        self.login_btn.SetForegroundColour(wx.WHITE)
        self.login_btn.SetMinSize((-1, 36))
        sz.Add(self.login_btn, 0, wx.EXPAND | wx.BOTTOM, 12)

        # Divider with "or"
        sep = wx.BoxSizer(wx.HORIZONTAL)
        sep.Add(wx.StaticLine(page), 1, wx.ALIGN_CENTER_VERTICAL)
        sep.Add(wx.StaticText(page, label="  or  "), 0, wx.ALIGN_CENTER_VERTICAL)
        sep.Add(wx.StaticLine(page), 1, wx.ALIGN_CENTER_VERTICAL)
        sz.Add(sep, 0, wx.EXPAND | wx.BOTTOM, 12)

        # Secondary button — Create Account
        self.to_reg_btn = wx.Button(page, label="Create Account", name="Create Account")
        self.to_reg_btn.SetMinSize((-1, 36))
        sz.Add(self.to_reg_btn, 0, wx.EXPAND)

        page.SetSizer(sz)
        self._book.AddPage(page, "Login")

        self.login_btn.Bind(wx.EVT_BUTTON, self.OnLogin)
        self.pass_ctrl.Bind(wx.EVT_TEXT_ENTER, self.OnLogin)
        self.user_ctrl.Bind(wx.EVT_TEXT_ENTER, lambda e: self.pass_ctrl.SetFocus())
        self.to_reg_btn.Bind(wx.EVT_BUTTON, lambda e: self._show_page(1))
        self.remember_cb.Bind(wx.EVT_CHECKBOX, self._on_remember_toggled)

    def _build_register_page(self):
        page = wx.Panel(self._book, name="Register Page")
        page.SetBackgroundColour(_BG)
        sz = wx.BoxSizer(wx.VERTICAL)

        hdr = wx.StaticText(page, label="Create your account")
        f = hdr.GetFont()
        f.SetPointSize(13)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        hdr.SetFont(f)
        hdr.SetForegroundColour(_TEXT)
        sz.Add(hdr, 0, wx.BOTTOM, 16)

        fields = [
            ("Skype Name",  "Reg Username", False),
            ("Password",    "Reg Password", True),
            ("Email",       "Reg Email",    False),
            ("First Name",  "Reg First",    False),
            ("Last Name",   "Reg Last",     False),
        ]
        self._reg_ctrls = []
        for label, name, is_pass in fields:
            lbl, ctrl = self._field(page, label, name, is_pass)
            sz.Add(lbl,  0, wx.BOTTOM, 3)
            sz.Add(ctrl, 0, wx.EXPAND | wx.BOTTOM, 9)
            self._reg_ctrls.append(ctrl)

        # Primary button
        self.do_reg_btn = wx.Button(page, label="Create Account", name="Register")
        self.do_reg_btn.SetDefault()
        self.do_reg_btn.SetBackgroundColour(_BLUE)
        self.do_reg_btn.SetForegroundColour(wx.WHITE)
        self.do_reg_btn.SetMinSize((-1, 36))
        sz.Add(self.do_reg_btn, 0, wx.EXPAND | wx.BOTTOM, 12)

        # Back link
        back_btn = wx.Button(page, label="Back to Sign In", name="Back to Login")
        back_btn.SetMinSize((-1, 32))
        sz.Add(back_btn, 0, wx.ALIGN_CENTER)

        page.SetSizer(sz)
        self._book.AddPage(page, "Register")

        self.do_reg_btn.Bind(wx.EVT_BUTTON, self.OnRegister)
        back_btn.Bind(wx.EVT_BUTTON, lambda e: self._show_page(0))

    def _prefill_saved_credentials(self):
        s = load_settings()
        if s.saved_username:
            self.user_ctrl.SetValue(s.saved_username)
            self.pass_ctrl.SetValue(s.saved_password)
            self.remember_cb.SetValue(True)

    def _on_remember_toggled(self, event):
        """Immediately clear saved credentials when the user unchecks Remember me."""
        if not self.remember_cb.IsChecked():
            s = load_settings()
            s.saved_username = ""
            s.saved_password = ""
            save_settings(s)

    def _show_page(self, idx: int):
        self.status_text.SetLabel("")
        self._book.SetSelection(idx)

    # ── Login ────────────────────────────────────────────────────────

    def OnLogin(self, event):
        username = self.user_ctrl.GetValue().strip()
        password = self.pass_ctrl.GetValue().strip()
        if not username or not password:
            self._set_status("Please enter your Skype Name and password.", error=True)
            return
        self._set_status("Signing in…")
        self.login_btn.Disable()
        threading.Thread(
            target=self._do_login, args=(username, password), daemon=True
        ).start()

    def _do_login(self, username: str, password: str):
        success, res = self.auth_service.login(username, password)
        wx.CallAfter(self._on_login_done, success, res)

    def _on_login_done(self, success: bool, res):
        if success:
            self._set_status("Signed in!", error=False)
            SoundPlayer().play(os.path.join("assets", "sounds", "misk_signin.wav"))
            # Save or clear credentials based on Remember Me
            s = load_settings()
            if self.remember_cb.IsChecked():
                s.saved_username = self.user_ctrl.GetValue().strip()
                s.saved_password = self.pass_ctrl.GetValue().strip()
            else:
                s.saved_username = ""
                s.saved_password = ""
            save_settings(s)
            self._on_login_success(res)
        else:
            self._set_status(f"Sign in failed: {res}", error=True)
            wx.MessageBox(
                f"Sign in failed.\n\n{res}",
                "Could Not Sign In",
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.login_btn.Enable()

    # ── Register ─────────────────────────────────────────────────────

    def OnRegister(self, event):
        keys = ["username", "password", "email", "first_name", "last_name"]
        data = {k: c.GetValue().strip() for k, c in zip(keys, self._reg_ctrls)}
        if any(not v for v in data.values()):
            self._set_status("All fields are required.", error=True)
            return
        self._set_status("Creating account…")
        self.do_reg_btn.Disable()
        threading.Thread(target=self._do_register, args=(data,), daemon=True).start()

    def _do_register(self, data: dict):
        success, msg = self.auth_service.register(data)
        wx.CallAfter(self._on_register_done, success, msg)

    def _on_register_done(self, success: bool, msg: str):
        self.do_reg_btn.Enable()
        self.status_text.SetLabel("")
        if success:
            for c in self._reg_ctrls:
                c.Clear()
            wx.MessageBox(
                "Your account has been created successfully!\n\nClick OK to sign in.",
                "Account Created",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self._show_page(0)
        else:
            wx.MessageBox(
                f"Registration failed:\n\n{msg}",
                "Could Not Create Account",
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def _set_status(self, msg: str, error: bool = False):
        self.status_text.SetLabel(msg)
        self.status_text.SetForegroundColour(_ERROR if error else _SUCCESS)
        self.status_text.GetParent().Layout()
