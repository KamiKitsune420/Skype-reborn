import wx
import structlog
from shared.models import SettingsPayload

logger = structlog.get_logger()

class SettingsFrame(wx.Frame):
    def __init__(self, parent, current_settings: SettingsPayload, on_save):
        super().__init__(parent, title="Skype™ Reborn — Settings", size=(400, 300))
        self.on_save = on_save
        self.settings = current_settings
        
        self.panel = wx.Panel(self)
        self.panel.SetName("Settings Panel")
        
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Audio Section
        audio_box = wx.StaticBox(self.panel, label="Audio Settings")
        audio_sizer = wx.StaticBoxSizer(audio_box, wx.VERTICAL)
        
        self.ptt_checkbox = wx.CheckBox(self.panel, label="Enable &Push-to-Talk")
        self.ptt_checkbox.SetValue(self.settings.push_to_talk)
        self.ptt_checkbox.SetName("Enable Push-to-Talk")
        audio_sizer.Add(self.ptt_checkbox, 0, wx.ALL, 5)
        
        self.sounds_checkbox = wx.CheckBox(self.panel, label="Enable &Notification Sounds")
        self.sounds_checkbox.SetValue(self.settings.notification_sounds)
        self.sounds_checkbox.SetName("Enable Notification Sounds")
        audio_sizer.Add(self.sounds_checkbox, 0, wx.ALL, 5)
        
        main_sizer.Add(audio_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Appearance Section
        theme_box = wx.StaticBox(self.panel, label="Appearance")
        theme_sizer = wx.StaticBoxSizer(theme_box, wx.VERTICAL)
        
        theme_label = wx.StaticText(self.panel, label="&Theme:")
        self.theme_choice = wx.Choice(self.panel, choices=["Classic", "Dark", "Modern"])
        self.theme_choice.SetStringSelection(self.settings.theme)
        self.theme_choice.SetName("Select Application Theme")
        
        theme_sizer.Add(theme_label, 0, wx.LEFT | wx.TOP, 5)
        theme_sizer.Add(self.theme_choice, 0, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(theme_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.save_btn = wx.Button(self.panel, label="&Save Settings")
        self.save_btn.SetDefault()
        self.cancel_btn = wx.Button(self.panel, label="&Cancel")
        
        btn_sizer.Add(self.save_btn, 0, wx.ALL, 5)
        btn_sizer.Add(self.cancel_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        self.panel.SetSizer(main_sizer)
        
        # Bindings
        self.save_btn.Bind(wx.EVT_BUTTON, self.OnSave)
        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        
        self.Centre()

    def OnSave(self, event):
        new_settings = SettingsPayload(
            push_to_talk=self.ptt_checkbox.GetValue(),
            notification_sounds=self.sounds_checkbox.GetValue(),
            theme=self.theme_choice.GetStringSelection()
        )
        self.on_save(new_settings)
        self.Close()
