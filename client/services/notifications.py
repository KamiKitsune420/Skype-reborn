from __future__ import annotations

from collections.abc import Callable

import wx
import wx.adv
import structlog

logger = structlog.get_logger()


class DesktopNotificationService:
    """Desktop attention and toast notifications for UI events."""

    def __init__(self, parent: wx.Frame):
        self.parent = parent

    def notify_chat_message(
        self,
        sender_name: str,
        content: str,
        play_sound: Callable[[], None] | None = None,
    ):
        if play_sound:
            play_sound()
        self.parent.RequestUserAttention(wx.USER_ATTENTION_INFO)
        if self.parent.IsIconized() or not self.parent.IsActive():
            self._show_toast(sender_name, content)

    def notify_incoming_call(self, caller_name: str):
        self.parent.RequestUserAttention(wx.USER_ATTENTION_ERROR)
        if self.parent.IsIconized() or not self.parent.IsActive():
            self._show_toast("Incoming call", caller_name)

    def notify_presence_change(self, name: str, is_online: bool):
        msg = f"{name} is now online" if is_online else f"{name} has gone offline"
        self._show_toast("Skype", msg)

    def _show_toast(self, title: str, message: str):
        try:
            note = wx.adv.NotificationMessage(title=title, message=message, parent=self.parent)
            note.Show(timeout=6)
        except Exception as exc:
            logger.debug("Desktop notification failed", error=str(exc))
