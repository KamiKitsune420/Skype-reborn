import wx
import wx.adv
import asyncio
from wxasync import AsyncBind
from ..network.api_client import APIClient
import os

class LoginFrame(wx.Frame):
    def __init__(self, api_client: APIClient, on_login_success):
        super().__init__(None, title="Skype™ Reborn - Login", size=(400, 650), 
                         style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX),
                         name="Skype Login Window")
        self.api_client = api_client
        self.on_login_success = on_login_success
        self.InitUI()
        self.Centre()

    def InitUI(self):
        self.panel = wx.Panel(self, name="Login Panel")
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)

        # Header Image
        header_path = os.path.join("assets", "images", "skype_header.png")
        if os.path.exists(header_path):
            img = wx.Image(header_path, wx.BITMAP_TYPE_ANY)
            w, h = img.GetSize()
            new_w = 400
            new_h = int(h * (new_w / w))
            img = img.Scale(new_w, new_h, wx.IMAGE_QUALITY_HIGH)
            sbmp = wx.StaticBitmap(self.panel, -1, wx.Bitmap(img), name="Skype Logo")
            self.main_vbox.Add(sbmp, 0, wx.EXPAND | wx.BOTTOM, 20)

        # --- Login View Container ---
        self.login_view = wx.Panel(self.panel)
        login_vbox = wx.BoxSizer(wx.VERTICAL)
        
        login_fgs = wx.FlexGridSizer(2, 2, 10, 25)
        self.user_label = wx.StaticText(self.login_view, label="&Skype Name", name="Skype Name Label")
        self.user_ctrl = wx.TextCtrl(self.login_view, name="Skype Name Input")
        
        self.pass_label = wx.StaticText(self.login_view, label="&Password", name="Password Label")
        self.pass_ctrl = wx.TextCtrl(self.login_view, style=wx.TE_PASSWORD, name="Password Input")
        
        # FlexGridSizer association: Label then Control
        login_fgs.Add(self.user_label, 0, wx.ALIGN_CENTER_VERTICAL)
        login_fgs.Add(self.user_ctrl, 1, wx.EXPAND)
        login_fgs.Add(self.pass_label, 0, wx.ALIGN_CENTER_VERTICAL)
        login_fgs.Add(self.pass_ctrl, 1, wx.EXPAND)
        
        login_fgs.AddGrowableCol(1, 1)
        login_vbox.Add(login_fgs, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 30)
        
        self.remember_cb = wx.CheckBox(self.login_view, label="&Remember me")
        login_vbox.Add(self.remember_cb, 0, wx.LEFT | wx.BOTTOM, 30)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.login_btn = wx.Button(self.login_view, label="&Sign in", size=(100, 35))
        self.login_btn.SetDefault()
        self.to_reg_btn = wx.Button(self.login_view, label="Create &account", size=(130, 35))
        btn_box.Add(self.to_reg_btn, 0, wx.RIGHT, 15)
        btn_box.Add(self.login_btn, 0)
        login_vbox.Add(btn_box, 0, wx.ALIGN_CENTER | wx.BOTTOM, 25)
        
        self.login_view.SetSizer(login_vbox)
        self.main_vbox.Add(self.login_view, 1, wx.EXPAND)

        # --- Register View Container ---
        self.register_view = wx.Panel(self.panel, name="Registration View")
        reg_vbox = wx.BoxSizer(wx.VERTICAL)
        reg_fgs = wx.FlexGridSizer(5, 2, 10, 25)
        
        self.reg_user_label = wx.StaticText(self.register_view, label="&Skype Name")
        self.reg_user = wx.TextCtrl(self.register_view, name="Reg Skype Name")
        
        self.reg_pass_label = wx.StaticText(self.register_view, label="&Password")
        self.reg_pass = wx.TextCtrl(self.register_view, style=wx.TE_PASSWORD, name="Reg Password")
        
        self.reg_email_label = wx.StaticText(self.register_view, label="&Email")
        self.reg_email = wx.TextCtrl(self.register_view, name="Reg Email")
        
        self.reg_fname_label = wx.StaticText(self.register_view, label="&First Name")
        self.reg_fname = wx.TextCtrl(self.register_view, name="Reg First Name")
        
        self.reg_lname_label = wx.StaticText(self.register_view, label="&Last Name")
        self.reg_lname = wx.TextCtrl(self.register_view, name="Reg Last Name")

        reg_fgs.Add(self.reg_user_label, 0, wx.ALIGN_CENTER_VERTICAL)
        reg_fgs.Add(self.reg_user, 1, wx.EXPAND)
        reg_fgs.Add(self.reg_pass_label, 0, wx.ALIGN_CENTER_VERTICAL)
        reg_fgs.Add(self.reg_pass, 1, wx.EXPAND)
        reg_fgs.Add(self.reg_email_label, 0, wx.ALIGN_CENTER_VERTICAL)
        reg_fgs.Add(self.reg_email, 1, wx.EXPAND)
        reg_fgs.Add(self.reg_fname_label, 0, wx.ALIGN_CENTER_VERTICAL)
        reg_fgs.Add(self.reg_fname, 1, wx.EXPAND)
        reg_fgs.Add(self.reg_lname_label, 0, wx.ALIGN_CENTER_VERTICAL)
        reg_fgs.Add(self.reg_lname, 1, wx.EXPAND)
        reg_fgs.AddGrowableCol(1, 1)
        reg_vbox.Add(reg_fgs, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 30)
        
        reg_btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.do_reg_btn = wx.Button(self.register_view, label="&Register", size=(100, 35), name="Register Action Button")
        self.back_btn = wx.Button(self.register_view, label="&Back", size=(100, 35), name="Back to Login Button")
        reg_btn_box.Add(self.back_btn, 0, wx.RIGHT, 15)
        reg_btn_box.Add(self.do_reg_btn, 0)
        reg_vbox.Add(reg_btn_box, 0, wx.ALIGN_CENTER | wx.BOTTOM, 25)
        
        self.register_view.SetSizer(reg_vbox)
        self.main_vbox.Add(self.register_view, 1, wx.EXPAND)
        self.register_view.Hide()

        # Status
        self.status_text = wx.StaticText(self.panel, label="", style=wx.ALIGN_CENTER)
        self.main_vbox.Add(self.status_text, 0, wx.ALIGN_CENTER | wx.TOP | wx.LEFT | wx.RIGHT, 10)

        self.panel.SetSizer(self.main_vbox)

        # Bindings
        AsyncBind(wx.EVT_BUTTON, self.OnLogin, self.login_btn)
        AsyncBind(wx.EVT_BUTTON, self.OnRegister, self.do_reg_btn)
        self.to_reg_btn.Bind(wx.EVT_BUTTON, lambda e: self.ShowRegister(True))
        self.back_btn.Bind(wx.EVT_BUTTON, lambda e: self.ShowRegister(False))

    def ShowRegister(self, show):
        self.login_view.Show(not show)
        self.register_view.Show(show)
        self.status_text.SetLabel("")
        self.panel.Layout()

    async def OnLogin(self, event):
        username = self.user_ctrl.GetValue().strip()
        password = self.pass_ctrl.GetValue().strip()
        
        if not username or not password:
            self.status_text.SetLabel("Enter Skype Name and password to sign in.")
            return

        self.status_text.SetLabel("Signing in...")
        self.login_btn.Disable()
        
        success, res = await self.api_client.login(username, password)
        if success:
            self.status_text.SetLabel("Success!")
            signin_sound = os.path.join("assets", "sounds", "misk_signin.wav")
            if os.path.exists(signin_sound):
                sound = wx.adv.Sound(signin_sound)
                if sound.IsOk(): sound.Play(wx.adv.SOUND_ASYNC)
            await self.on_login_success(res)
        else:
            self.status_text.SetLabel(f"Sign in failed: {res}")
            self.login_btn.Enable()

    async def OnRegister(self, event):
        data = {
            "username": self.reg_user.GetValue().strip(),
            "password": self.reg_pass.GetValue().strip(),
            "email": self.reg_email.GetValue().strip(),
            "first_name": self.reg_fname.GetValue().strip(),
            "last_name": self.reg_lname.GetValue().strip()
        }

        if any(not v for v in data.values()):
            self.status_text.SetLabel("All fields are required for registration.")
            return

        self.status_text.SetLabel("Creating account...")
        success, msg = await self.api_client.register(data)
        if success:
            self.status_text.SetLabel("Account created. You can now sign in.")
            self.ShowRegister(False)
        else:
            self.status_text.SetLabel(f"Failed: {msg}")
