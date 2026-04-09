"""
Emergency Phone Call Notifier
Triggers an automated Twilio voice call when an accident is detected.
One call per incident — cooldown prevents duplicate calls.
"""

import logging
import threading
import time

logger = logging.getLogger("resq_vision.notifier")

import os
from dotenv import load_dotenv

load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = "+16615184795"
TO_NUMBER   = "+918310319012"

# Cooldown: don't call again within this many seconds
CALL_COOLDOWN_SECONDS = 60

_last_call_time: float = 0.0
_lock = threading.Lock()


def _make_call(incident: dict) -> None:
    try:
        from twilio.rest import Client
        from twilio.twiml.voice_response import VoiceResponse

        severity       = incident.get("severity", "Major")
        collision_type = incident.get("collision_type", "vehicle collision")
        incident_id    = incident.get("incident_id", "unknown")

        print(f"[NOTIFIER] Placing emergency call for {incident_id} ({severity})...", flush=True)

        vr = VoiceResponse()
        vr.say(
            f"Alert! Rescue Vision has detected an accident. "
            f"Incident {incident_id}. "
            f"Severity: {severity}. "
            f"Type: {collision_type}. "
            f"Emergency response has been dispatched. Please take immediate action.",
            voice="alice",
            language="en-IN",
        )

        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        call = client.calls.create(
            twiml=str(vr),
            to=TO_NUMBER,
            from_=FROM_NUMBER,
        )
        print(f"[NOTIFIER] Call placed — SID={call.sid} status={call.status}", flush=True)

    except Exception as e:
        print(f"[NOTIFIER] ERROR placing call: {e}", flush=True)


def notify_accident(incident: dict) -> None:
    """
    Triggers a phone call in a background thread.
    Silently skips if a call was already made within CALL_COOLDOWN_SECONDS.
    """
    global _last_call_time

    with _lock:
        now = time.time()
        if now - _last_call_time < CALL_COOLDOWN_SECONDS:
            remaining = CALL_COOLDOWN_SECONDS - (now - _last_call_time)
            print(f"[NOTIFIER] Call skipped — cooldown active ({remaining:.0f}s remaining)", flush=True)
            return
        _last_call_time = now

    t = threading.Thread(target=_make_call, args=(incident,), daemon=False)
    t.start()
