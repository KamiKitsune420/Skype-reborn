import wx


class CallsController:
    def __init__(self, owner):
        self.owner = owner

    def start_call(self, event=None):
        owner = self.owner
        if owner.is_calling:
            self.hang_up()
            return
        if not owner.selected_contact:
            return

        name = owner.selected_contact["display_name"]
        owner.call_contact_lbl.SetLabel(name)
        owner.call_status_text.SetLabel("Calling...")
        owner.is_calling = True

        owner._show_view(owner.VIEW_CALL)
        owner.play_sound("call_request_sent.wav")

        owner.call_service.start_outgoing(owner.selected_contact["id"], name)
        owner._call_timer.StartOnce(30_000)

    def on_timeout(self, event):
        owner = self.owner
        if owner.is_calling:
            owner.call_status_text.SetLabel("No answer.")
            self.hang_up()

    def toggle_mute(self, event=None):
        owner = self.owner
        if owner.audio_engine._muted:
            owner.audio_engine.unmute()
            owner.mute_btn.SetLabel("Mute Microphone")
        else:
            owner.audio_engine.mute()
            owner.mute_btn.SetLabel("Unmute Microphone")

    def hang_up(self):
        owner = self.owner
        owner._call_timer.Stop()
        owner.call_service.hang_up()
        self.stop_call(already_stopped=True)

    def stop_call(self, already_stopped: bool = False):
        owner = self.owner
        owner._call_timer.Stop()
        owner.stop_looping_sound()
        if not already_stopped:
            owner.call_service.end_local()
        owner.is_calling = False
        owner._call_minimized = False
        owner.mute_btn.SetLabel("Mute Microphone")
        owner.play_sound("call_end.wav")
        if hasattr(owner, "_incoming_call"):
            del owner._incoming_call
        owner._show_view(owner.VIEW_CONTACTS)

    def answer_call(self, payload):
        owner = self.owner
        owner._call_timer.Stop()
        owner.stop_looping_sound()
        owner.play_sound("Call_Answer.wav")

        sender_name = next(
            (c["display_name"] for c in owner.contacts if c["id"] == payload.sender_id),
            "Contact",
        )
        owner.call_service.accept(payload, sender_name)
        owner.is_calling = True
        owner.call_contact_lbl.SetLabel(sender_name)
        owner.call_status_text.SetLabel("In call")
        owner._show_view(owner.VIEW_CALL)
