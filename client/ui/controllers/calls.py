import datetime

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
        owner._call_peer_id = owner.selected_contact["id"]
        owner._call_peer_name = name
        owner._call_is_incoming = False

        owner._show_view(owner.VIEW_CALL)
        owner.play_sound("call_connecting.wav")          # play immediately
        owner._ring_timer.Start(2500)                    # then every 2.5 s

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
        owner._ring_timer.Stop()
        owner.stop_looping_sound()
        if not already_stopped:
            owner.call_service.end_local()
        # Log call record before clearing state
        start = getattr(owner, "_call_start_time", None)
        if start is not None:
            duration = datetime.datetime.now() - start
            owner.messages_controller.append_call_record(
                getattr(owner, "_call_peer_id", None),
                getattr(owner, "_call_peer_name", "Contact"),
                getattr(owner, "_call_is_incoming", False),
                duration,
            )
            owner._call_start_time = None
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
        owner._call_peer_id = payload.sender_id
        owner._call_peer_name = sender_name
        owner._call_is_incoming = True
        owner._call_start_time = datetime.datetime.now()
        owner.call_contact_lbl.SetLabel(sender_name)
        owner.call_status_text.SetLabel("In call")
        # Apply mute if requested before answering
        if getattr(owner, "_mute_on_answer", False):
            owner.audio_engine.mute()
            owner.mute_btn.SetLabel("Unmute Microphone")
            owner._mute_on_answer = False
        owner._show_view(owner.VIEW_CALL)
