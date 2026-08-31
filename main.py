import os
import json
from datetime import datetime
from typing import Dict, Any
from fastapi import FastAPI, BackgroundTasks
import anthropic
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = FastAPI(title="Estetik International - Voice Match & Calendar Bridge")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


@app.get("/")
def health_check():
    return {"status": "ok", "service": "Estetik International Voice Bridge"}


# -------------------------------------------------------------
# 1. Voice Match & Dynamic Variable Injection
# -------------------------------------------------------------
@app.post("/inbound-call")
async def handle_inbound_call(payload: Dict[str, Any]):
    matched_voice_id = "21m00Tcm4TlvDq8ikWAM"
    customer_name = "Değerli Danışanımız"
    treatment_interest = "Second Prime"

    return {
        "dynamic_variables": {
            "customer_name": customer_name,
            "treatment_interest": treatment_interest,
            "company_name": "Estetik International"
        },
        "conversation_config_override": {
            "tts": {
                "voice_id": matched_voice_id
            }
        }
    }


# -------------------------------------------------------------
# 2. Post-Call Webhook & Claude Calendar Integration
# -------------------------------------------------------------
async def process_call_summary_and_calendar(payload: Dict[str, Any]):
    try:
        analysis = payload.get("analysis", {})
        data_collection = analysis.get("data_collection_results", {})
        transcript_summary = analysis.get("transcript_summary", "")

        client_name = data_collection.get("client_name", {}).get("value") or "Bilinmeyen Danışan"
        phone = data_collection.get("client_phone_number", {}).get("value") or ""
        interest = data_collection.get("primary_interest", {}).get("value") or "Second Prime"
        raw_date_time = (
            data_collection.get("consultation_date_time", {}).get("value")
            or data_collection.get("availability_stated", {}).get("value")
            or "Tarih belirtilmedi"
        )
        call_outcome = data_collection.get("call_outcome", {}).get("value") or ""

        if not claude_client:
            print("Hata: ANTHROPIC_API_KEY tanımlı değil.")
            return

        prompt = f"""
        Aşağıdaki Estetik International telefon görüşme analizini incele:
        - Danışan: {client_name}
        - İlgilendiği Alan / Prosedür: {interest}
        - Görüşmede Belirtilen Tarih/Saat: {raw_date_time}
        - Görüşme Özeti: {transcript_summary}
        - Görüşme Sonucu: {call_outcome}
        - Bugünün Tarihi: {datetime.utcnow().strftime('%Y-%m-%d')}

        Görevin: Eğer danışan bir randevu/konsültasyon veya geri arama için tarih/saat belirttiyse, Türkiye saatine (UTC+3) uygun ISO-8601 tarih formatı üret.
        SADECE aşağıdaki JSON formatında yanıt ver:
        {{
            "should_create_calendar_event": true,
            "start_time_iso": "YYYY-MM-DDTHH:MM:SS+03:00",
            "end_time_iso": "YYYY-MM-DDTHH:MM:SS+03:00",
            "event_title": "Second Prime Video Konsültasyon - {client_name}",
            "description": "Danışan: {client_name}\\nTelefon: {phone}\\nİlgi: {interest}\\nÖzet: {transcript_summary}"
        }}
        """

        response = claude_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = response.content[0].text.strip()
        parsed_result = json.loads(result_text)

        if parsed_result.get("should_create_calendar_event") and parsed_result.get("start_time_iso"):
            if GOOGLE_SERVICE_ACCOUNT_JSON:
                creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
                creds = Credentials.from_service_account_info(
                    creds_dict, scopes=["https://www.googleapis.com/auth/calendar"]
                )
                service = build("calendar", "v3", credentials=creds)

                event = {
                    "summary": parsed_result.get("event_title"),
                    "description": parsed_result.get("description"),
                    "start": {"dateTime": parsed_result.get("start_time_iso")},
                    "end": {"dateTime": parsed_result.get("end_time_iso")},
                }

                service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
                print(f"Google Calendar randevusu oluşturuldu: {client_name}")

    except Exception as e:
        print(f"Hata: {str(e)}")


@app.post("/post-call-webhook")
async def handle_post_call(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    background_tasks.add_task(process_call_summary_and_calendar, payload)
    return {"status": "received"}
