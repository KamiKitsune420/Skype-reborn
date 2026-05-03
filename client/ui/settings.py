"""Settings dialog — Audio, Appearance, Devices tabs."""
import os
import threading
import wave
import numpy as np
import structlog
import wx
import sounddevice as sd
from shared.models import SettingsPayload

logger = structlog.get_logger()

_BLUE = wx.Colour(0, 120, 212)
_SOUNDS_DIR = os.path.join("assets", "sounds")


def _read_wav(path: str):
    """Read a WAV file of any standard bit depth and return (float32_array, sample_rate)."""
    with wave.open(path, "rb") as wf:
        n_frames  = wf.getnframes()
        n_ch      = wf.getnchannels()
        sw        = wf.getsampwidth()   # bytes per sample
        fs        = wf.getframerate()
        raw       = wf.readframes(n_frames)

    if sw == 1:                         # 8-bit unsigned
        s = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0
    elif sw == 2:                       # 16-bit signed LE
        s = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 3:                       # 24-bit signed LE — 3 bytes per sample
        raw_u8 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        i32 = (raw_u8[:, 0].astype(np.int32) |
               (raw_u8[:, 1].astype(np.int32) << 8) |
               (raw_u8[:, 2].astype(np.int32) << 16))
        i32[i32 >= (1 << 23)] -= (1 << 24)   # sign-extend
        s = i32.astype(np.float32) / (1 << 23)
    elif sw == 4:                       # 32-bit signed LE
        s = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2**31
    else:
        raise ValueError(f"Unsupported WAV sample width: {sw} bytes")

    if n_ch > 1:
        s = s.reshape(-1, n_ch)
    return s, fs


def _clean_name(name: str) -> str:
    """Remove doubled suffixes like 'Foo (Foo)' that PortAudio produces on Windows."""
    if "(" in name and name.endswith(")"):
        inner = name[name.rfind("(") + 1 : -1].strip()
        outer = name[: name.rfind("(")].strip()
        if outer == inner:
            return outer
    return name


_SKIP_PREFIXES = (
    "Primary Sound",
    "Microsoft Sound Mapper",
)
_SKIP_SUBSTRINGS = (
    "PC Speaker",
    "SPDIF",
)


def _is_usable(name: str) -> bool:
    for p in _SKIP_PREFIXES:
        if name.startswith(p):
            return False
    for s in _SKIP_SUBSTRINGS:
        if s in name:
            return False
    return True


def _query_devices():
    try:
        devs = sd.query_devices()
        seen_in, seen_out = set(), set()
        inputs, outputs = ["Default"], ["Default"]
        for d in devs:
            raw = d["name"]
            name = _clean_name(raw)
            if not _is_usable(name):
                continue
            if d["max_input_channels"] > 0 and name not in seen_in:
                inputs.append(name)
                seen_in.add(name)
            if d["max_output_channels"] > 0 and name not in seen_out:
                outputs.append(name)
                seen_out.add(name)
    except Exception:
        inputs = outputs = ["Default"]
    return inputs, outputs


# Ordered mapping: filename → display name shown in the settings UI.
_RINGTONES: dict[str, str] = {
    "call_ring1.wav": "Skype (Classic)",
    "call_ring2.wav": "Skype (Metro)",
    "call_ring3.wav": "Microsoft Teams (PC)",
    "call_ring4.wav": "Microsoft Teams (Mobile)",
}
_RINGTONE_LABELS = list(_RINGTONES.values())
_RINGTONE_FILES  = list(_RINGTONES.keys())

def _label_to_file(label: str) -> str:
    """Return the filename for a given display label, defaulting to the first."""
    for f, l in _RINGTONES.items():
        if l == label:
            return f
    return _RINGTONE_FILES[0]

def _file_to_label(filename: str) -> str:
    """Return the display label for a given filename, defaulting to the first."""
    return _RINGTONES.get(filename, _RINGTONE_LABELS[0])


class SettingsDialog(wx.Dialog):
    """Application settings — opened with ShowModal()."""

    def __init__(self, parent, current_settings: SettingsPayload, on_save):
        super().__init__(
            parent,
            title="Skype™ Reborn — Settings",
            size=(500, 400),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name="Settings Dialog",
        )
        self.on_save   = on_save
        self.settings  = current_settings
        self._test_thd = None
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.WHITE)
        root = wx.BoxSizer(wx.VERTICAL)

        book = wx.Notebook(panel)

        # ── Audio tab ────────────────────────────────────────────────
        audio_pg = wx.Panel(book)
        ap = wx.BoxSizer(wx.VERTICAL)
        ap.Add(wx.StaticText(audio_pg, label="Voice & Sounds"), 0, wx.LEFT | wx.TOP, 16)
        ap.Add(wx.StaticLine(audio_pg), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        self.ptt_cb = wx.CheckBox(audio_pg, label="Enable Push-to-Talk (hold Space to speak)", name="PTT")
        self.ptt_cb.SetValue(self.settings.push_to_talk)
        ap.Add(self.ptt_cb, 0, wx.ALL, 16)

        self.sounds_cb = wx.CheckBox(audio_pg, label="Enable notification sounds", name="Sounds")
        self.sounds_cb.SetValue(self.settings.notification_sounds)
        ap.Add(self.sounds_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)

        ap.Add(wx.StaticText(audio_pg, label="Ringtone:"), 0, wx.LEFT, 16)
        rt_row = wx.BoxSizer(wx.HORIZONTAL)
        self.ringtone_choice = wx.Choice(audio_pg, choices=_RINGTONE_LABELS, name="Ringtone")
        self.ringtone_choice.SetStringSelection(_file_to_label(self.settings.ringtone))
        self.preview_btn = wx.Button(audio_pg, label="Preview", name="Preview Ringtone")
        rt_row.Add(self.ringtone_choice, 1, wx.RIGHT, 8)
        rt_row.Add(self.preview_btn, 0)
        ap.Add(rt_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        audio_pg.SetSizer(ap)
        book.AddPage(audio_pg, "Audio")

        # ── Devices tab ──────────────────────────────────────────────
        dev_pg = wx.Panel(book)
        dp = wx.BoxSizer(wx.VERTICAL)
        dp.Add(wx.StaticText(dev_pg, label="Audio Devices"), 0, wx.LEFT | wx.TOP, 16)
        dp.Add(wx.StaticLine(dev_pg), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

        inputs, outputs = _query_devices()

        dp.Add(wx.StaticText(dev_pg, label="Input device (microphone):"), 0, wx.LEFT | wx.TOP, 16)
        self.input_choice = wx.Choice(dev_pg, choices=inputs, name="Input Device")
        if self.settings.input_device in inputs:
            self.input_choice.SetStringSelection(self.settings.input_device)
        else:
            self.input_choice.SetSelection(0)
        dp.Add(self.input_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        dp.Add(wx.StaticText(dev_pg, label="Output device (speakers/headphones):"), 0, wx.LEFT | wx.TOP, 16)
        self.output_choice = wx.Choice(dev_pg, choices=outputs, name="Output Device")
        if self.settings.output_device in outputs:
            self.output_choice.SetStringSelection(self.settings.output_device)
        else:
            self.output_choice.SetSelection(0)
        dp.Add(self.output_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        self.test_btn = wx.Button(dev_pg, label="Test Output Device (plays ringtone)", name="Test Device")
        dp.Add(self.test_btn, 0, wx.LEFT | wx.TOP, 16)

        dp.Add(wx.StaticText(dev_pg, label="Camera:"), 0, wx.LEFT | wx.TOP, 16)
        self.camera_choice = wx.Choice(dev_pg, choices=["Default", "Built-in Camera"], name="Camera")
        dp.Add(self.camera_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        dev_pg.SetSizer(dp)
        book.AddPage(dev_pg, "Devices")

        # ── Appearance tab ───────────────────────────────────────────
        app_pg = wx.Panel(book)
        app_sz = wx.BoxSizer(wx.VERTICAL)
        app_sz.Add(wx.StaticText(app_pg, label="Visual Style"), 0, wx.LEFT | wx.TOP, 16)
        app_sz.Add(wx.StaticLine(app_pg), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)
        app_sz.Add(wx.StaticText(app_pg, label="Theme:"), 0, wx.LEFT | wx.TOP, 16)
        self.theme_choice = wx.Choice(app_pg, choices=["Classic", "Dark", "Modern"], name="Theme")
        self.theme_choice.SetStringSelection(self.settings.theme)
        app_sz.Add(self.theme_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        note = wx.StaticText(app_pg, label="Restart Skype Reborn for theme changes to take full effect.")
        f = note.GetFont(); f.SetPointSize(8); note.SetFont(f)
        note.SetForegroundColour(wx.Colour(96, 94, 92))
        app_sz.Add(note, 0, wx.LEFT | wx.TOP, 16)
        app_pg.SetSizer(app_sz)
        book.AddPage(app_pg, "Appearance")

        root.Add(book, 1, wx.EXPAND | wx.ALL, 8)
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

        save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: (self._stop_test(), self.EndModal(wx.ID_CANCEL)))
        self.preview_btn.Bind(wx.EVT_BUTTON, self._on_preview_ringtone)
        self.test_btn.Bind(wx.EVT_BUTTON, self._on_test_device)
        self.Bind(wx.EVT_CLOSE, lambda e: (self._stop_test(), e.Skip()))

    # ── Ringtone preview ─────────────────────────────────────────────

    def _on_preview_ringtone(self, event):
        if self.preview_btn.GetLabel() == "Stop Preview":
            self._reset_buttons()
            sd.stop()
            return
        ringtone = _label_to_file(self.ringtone_choice.GetStringSelection())
        path = os.path.join(_SOUNDS_DIR, ringtone)
        if not os.path.exists(path):
            wx.MessageBox(f"Ringtone file not found:\n{path}", "Error",
                          wx.OK | wx.ICON_ERROR, self)
            return
        sd.stop()  # stop any existing playback without touching labels yet
        self._reset_buttons()
        self.preview_btn.SetLabel("Stop Preview")
        self._test_thd = threading.Thread(target=self._play_test, args=(path,), daemon=True)
        self._test_thd.start()

    # ── Device test ───────────────────────────────────────────────────

    def _on_test_device(self, event):
        if self.test_btn.GetLabel() == "Stop Test":
            self._reset_buttons()
            sd.stop()
            return
        ringtone = _label_to_file(self.ringtone_choice.GetStringSelection())
        path = os.path.join(_SOUNDS_DIR, ringtone)
        if not os.path.exists(path):
            wx.MessageBox(f"Ringtone file not found:\n{path}", "Error",
                          wx.OK | wx.ICON_ERROR, self)
            return
        sd.stop()
        self._reset_buttons()
        self.test_btn.SetLabel("Stop Test")
        self._test_thd = threading.Thread(target=self._play_test, args=(path,), daemon=True)
        self._test_thd.start()

    def _play_test(self, path: str):
        try:
            data, fs = _read_wav(path)
            dev_name = self.output_choice.GetStringSelection()
            dev = None if dev_name == "Default" else dev_name
            sd.play(data, fs, device=dev, loop=True)
            sd.wait()
        except Exception as e:
            logger.warning("Device test failed", error=str(e))
        finally:
            wx.CallAfter(self._reset_buttons)

    def _reset_buttons(self):
        """Reset both playback buttons to their default labels (safe from any thread)."""
        self.preview_btn.SetLabel("Preview")
        self.test_btn.SetLabel("Test Output Device (plays ringtone)")

    def _stop_test(self):
        sd.stop()
        wx.CallAfter(self._reset_buttons)

    # ── Save ──────────────────────────────────────────────────────────

    def _on_save(self, event):
        self._stop_test()
        new_settings = SettingsPayload(
            push_to_talk=self.ptt_cb.GetValue(),
            notification_sounds=self.sounds_cb.GetValue(),
            theme=self.theme_choice.GetStringSelection(),
            ringtone=_label_to_file(self.ringtone_choice.GetStringSelection()),
            input_device=self.input_choice.GetStringSelection(),
            output_device=self.output_choice.GetStringSelection(),
            camera_device=self.camera_choice.GetStringSelection(),
        )
        self.on_save(new_settings)
        self.EndModal(wx.ID_OK)
