"""
AquaAI Monitor — Backend Server
Run: uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from datetime import datetime
import os, random, asyncio

# ─── CONFIG (fill in your Twilio credentials) ────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN",  "your_auth_token_here")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+1415XXXXXXX")   # Your Twilio number
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="AquaAI Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # In production, restrict to your domain
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
app.mount("/static", StaticFiles(directory="../frontend"), name="static")

# ─── MODELS ──────────────────────────────────────────────────────────────────

class SMSRequest(BaseModel):
    to:      str          # Registered phone number  e.g. "+919876543210"
    message: str          # SMS body text
    alert_type: str = "info"   # "leak" | "overuse" | "valve" | "info" | "test"

class PhoneRegister(BaseModel):
    phone: str            # Full number with country code

class SensorData(BaseModel):
    flow_rate: float
    pressure:  float
    valve_open: bool
    daily_usage: float

# ─── IN-MEMORY STORE ─────────────────────────────────────────────────────────

registered_phones: dict[str, dict] = {}   # phone -> {registered_at, sms_count}
sms_log: list[dict] = []

# ─── TWILIO SMS SENDER ───────────────────────────────────────────────────────

def send_twilio_sms(to: str, body: str) -> dict:
    """Send a real SMS via Twilio. Returns status dict."""
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=TWILIO_FROM_NUMBER,
            to=to
        )
        return {
            "success": True,
            "sid": message.sid,
            "status": message.status,
            "to": to,
            "sent_at": datetime.now().isoformat()
        }
    except TwilioRestException as e:
        return {
            "success": False,
            "error": str(e),
            "code": e.code,
            "to": to
        }
    except Exception as e:
        return {"success": False, "error": str(e), "to": to}

# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.get("/")
def serve_frontend():
    return FileResponse("../frontend/index.html")

@app.post("/api/register-phone")
def register_phone(data: PhoneRegister):
    """Register a phone number for SMS alerts."""
    phone = data.phone.strip()
    if not phone.startswith("+"):
        raise HTTPException(400, "Phone must include country code, e.g. +919876543210")

    registered_phones[phone] = {
        "registered_at": datetime.now().isoformat(),
        "sms_count": 0
    }

    # Send welcome SMS
    welcome = (
        f"👋 Welcome to AquaAI Monitor!\n"
        f"Your phone {phone} is now registered.\n"
        f"You will receive alerts for:\n"
        f"🚨 Pipe leaks\n"
        f"📊 High water usage\n"
        f"🔧 Valve changes\n"
        f"Reply STOP to unsubscribe."
    )
    result = send_twilio_sms(phone, welcome)

    return {
        "registered": True,
        "phone": phone,
        "sms_result": result
    }

@app.post("/api/send-sms")
def send_sms(req: SMSRequest):
    """Send an SMS alert to the registered phone number."""
    to = req.to.strip()

    # Update counter
    if to in registered_phones:
        registered_phones[to]["sms_count"] += 1

    result = send_twilio_sms(to, req.message)

    # Log it
    sms_log.append({
        "to": to,
        "message": req.message,
        "alert_type": req.alert_type,
        "result": result,
        "timestamp": datetime.now().isoformat()
    })

    if not result["success"]:
        raise HTTPException(500, f"SMS failed: {result.get('error')}")

    return result

@app.post("/api/alert/leak")
def leak_alert(data: SensorData):
    """AI leak detection endpoint — call this from your sensor loop."""
    msg = (
        f"🚨 AquaAI LEAK ALERT!\n"
        f"Pipe leak detected at {datetime.now().strftime('%H:%M:%S')}.\n"
        f"Flow: {data.flow_rate:.1f} L/min (abnormal)\n"
        f"Pressure: {data.pressure:.1f} bar (dropped)\n"
        f"Valve: {'OPEN' if data.valve_open else 'AUTO-CLOSED'}\n"
        f"Action: Check your pipes immediately!"
    )
    results = []
    for phone in registered_phones:
        results.append(send_twilio_sms(phone, msg))
    return {"alerts_sent": len(results), "results": results}

@app.post("/api/alert/overuse")
def overuse_alert(data: SensorData):
    """Overuse detection — sends SMS when daily limit exceeded."""
    pct = round(data.daily_usage / 200 * 100)
    msg = (
        f"⚠️ AquaAI HIGH USAGE ALERT!\n"
        f"Daily water usage: {data.daily_usage:.0f}L ({pct}% of 200L limit)\n"
        f"Current flow: {data.flow_rate:.1f} L/min\n"
        f"Time: {datetime.now().strftime('%H:%M:%S')}\n"
        f"Tip: Turn off taps you don't need!"
    )
    results = []
    for phone in registered_phones:
        results.append(send_twilio_sms(phone, msg))
    return {"alerts_sent": len(results), "results": results}

@app.get("/api/sms-log")
def get_sms_log():
    return {"total": len(sms_log), "log": sms_log[-20:]}

@app.get("/api/status")
def status():
    return {
        "status": "online",
        "registered_phones": len(registered_phones),
        "sms_sent_total": len(sms_log),
        "twilio_from": TWILIO_FROM_NUMBER,
        "time": datetime.now().isoformat()
    }
