import os
import wx
import wx.adv


class MainTrayIcon(wx.adv.TaskBarIcon):
    """System tray icon that restores or exits the main window."""

    def __init__(self, window: wx.Frame):
        super().__init__()
        self.window = window
        self.SetIcon(self._load_icon(), "Skype Reborn")
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self._on_show)

    def CreatePopupMenu(self) -> wx.Menu:
        menu = wx.Menu()
        show_item = menu.Append(wx.ID_ANY, "Show Skype Reborn")
        exit_item = menu.Append(wx.ID_ANY, "Exit Skype Reborn")
        menu.Bind(wx.EVT_MENU, self._on_show, show_item)
        menu.Bind(wx.EVT_MENU, self._on_exit, exit_item)
        return menu

    def _on_show(self, event):
        self.window.restore_from_tray()

    def _on_exit(self, event):
        self.window.exit_application()

    def _load_icon(self) -> wx.Icon:
        size = max(wx.SystemSettings.GetMetric(wx.SYS_SMALLICON_X), 16)
        icon = wx.Icon()
        candidates = [
            os.path.join("assets", "images", "skype_logo_mini.png"),
            os.path.join("assets", "images", "white_skype.png"),
            os.path.join("assets", "images", "skype_header_round_border.png"),
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            img = wx.Image(path, wx.BITMAP_TYPE_ANY)
            if not img.IsOk():
                continue
            bmp = wx.Bitmap(img.Scale(size, size, wx.IMAGE_QUALITY_HIGH))
            icon.CopyFromBitmap(bmp)
            if icon.IsOk():
                return icon
        fallback = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_OTHER, (size, size))
        icon.CopyFromBitmap(fallback)
        return icon
