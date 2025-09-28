# -*- coding: utf-8 -*-
import requests
import pandas as pd
from typing import List, Dict, Optional
import time
import logging
import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class AirQualityMonitor:
    def __init__(self,
                 service_account_path: str,
                 airvisual_api_key: str,
                 ultramsg_token: str,
                 ultramsg_instance: str):
        """
        Initialize the Air Quality Monitor
        """
        self.service_account_path = service_account_path
        self.airvisual_api_key = airvisual_api_key
        self.ultramsg_token = ultramsg_token
        self.ultramsg_instance = ultramsg_instance
        self.dashboard_link = "https://airq.lovable.app/"

        # Initialize Google Sheets service
        self.sheets_service = self._init_sheets_service()

    def _init_sheets_service(self):
        """Initialize Google Sheets API service"""
        try:
            credentials = Credentials.from_service_account_file(
                self.service_account_path,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            service = build('sheets', 'v4', credentials=credentials)
            logger.info("✅ Google Sheets API service initialized successfully")
            return service
        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Sheets service: {e}")
            return None

    def get_google_sheets_data(self, spreadsheet_id: str, sheet_name: str = "Sheet1") -> List[Dict]:
        """Fetch data from Google Sheets"""
        try:
            if not self.sheets_service:
                logger.error("Google Sheets service not initialized")
                return []

            range_name = f"{sheet_name}!A1:G"
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()

            values = result.get('values', [])
            if not values:
                logger.warning("⚠️ No data found in spreadsheet")
                return []

            headers = values[0]
            data_rows = values[1:]

            users_data = []
            for row in data_rows:
                while len(row) < len(headers):
                    row.append("")
                user_dict = {
                    "submission_id": row[0] if len(row) > 0 else "",
                    "respondent_id": row[1] if len(row) > 1 else "",
                    "submitted_at": row[2] if len(row) > 2 else "",
                    "name": row[3] if len(row) > 3 else "",
                    "city": row[4] if len(row) > 4 else "",
                    "notification": row[5] if len(row) > 5 else "",
                    "whatsapp_number": row[6] if len(row) > 6 else ""
                }
                users_data.append(user_dict)

            logger.info(f"✅ Retrieved {len(users_data)} rows from Google Sheets")
            return users_data

        except Exception as e:
            logger.error(f"❌ Error reading Google Sheets: {e}")
            return []

    def filter_notification_enabled_users(self, data: List[Dict]) -> List[Dict]:
        """Filter users who enabled notifications"""
        filtered = [user for user in data if user.get("notification") == "Yes"]
        logger.info(f"ℹ️ Found {len(filtered)} users with notifications enabled")
        return filtered

    def get_coordinates_from_city(self, city: str) -> Optional[Dict]:
        """Get coordinates from city name"""
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": city, "format": "json", "limit": 1}
            headers = {"User-Agent": "AirQBot"}

            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()

            data = response.json()
            if data:
                coords = {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"])}
                logger.info(f"📍 Got coordinates for {city}: {coords}")
                return coords
            logger.warning(f"⚠️ No coordinates found for {city}")
            return None

        except Exception as e:
            logger.error(f"❌ Error getting coordinates for {city}: {e}")
            return None

    def get_air_quality_data(self, lat: float, lon: float) -> Optional[Dict]:
        """Get air quality data from AirVisual API"""
        try:
            url = "http://api.airvisual.com/v2/nearest_city"
            params = {"lat": lat, "lon": lon, "key": self.airvisual_api_key}

            response = requests.get(url, params=params)
            logger.info(f"🌍 AirVisual response: {response.status_code}")
            logger.debug(f"Response body: {response.text}")
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"❌ Error getting air quality data: {e}")
            return None

    def send_whatsapp_message(self, phone_number: str, message: str) -> bool:
        """Send WhatsApp message using UltraMsg API"""
        try:
            url = f"https://api.ultramsg.com/{self.ultramsg_instance}/messages/chat"
            data = {"token": self.ultramsg_token, "to": f"+{phone_number}", "body": message}

            logger.info(f"📲 Sending message to {phone_number} ...")
            response = requests.post(url, data=data)
            logger.info(f"UltraMsg response status: {response.status_code}")
            logger.info(f"UltraMsg response body: {response.text}")

            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"❌ Error sending message to {phone_number}: {e}")
            return False

    def get_aqi_message(self, city: str, aqi: int) -> Optional[str]:
        """Generate AQI message"""
        if 101 <= aqi <= 200:
            return f"""⚠️ Hey there!

The air in {city} isn't looking good 🚩 AQI {aqi} – Unhealthy.
Better to stay indoors and avoid heavy outdoor activities.

👉 Live dashboard:
{self.dashboard_link}?city={city}"""

        elif 201 <= aqi <= 300:
            return f"""⚠️ Attention! The air in {city} is 🚩 AQI {aqi} – Very Unhealthy.
Safer to stay indoors and wear N95 if you go out.

👉 Live dashboard:
{self.dashboard_link}?city={city}"""

        elif aqi >= 301:
            return f"""🛑 ALERT! {city} just reached 🚩 AQI {aqi} – Hazardous.
Stay indoors, avoid going outside, seek medical help if unwell.

👉 Live dashboard:
{self.dashboard_link}?city={city}"""

        return None

    def process_user(self, user: Dict) -> bool:
        """Process single user"""
        try:
            city = user.get("city")
            phone_number = user.get("whatsapp_number")
            name = user.get("name")

            if not city or not phone_number:
                logger.warning(f"⚠️ Missing city or phone number for {name}")
                return False

            logger.info(f"👤 Processing user {name}, city={city}, phone={phone_number}")

            coordinates = self.get_coordinates_from_city(city)
            if not coordinates:
                return False

            air_quality = self.get_air_quality_data(coordinates["lat"], coordinates["lon"])
            if not air_quality or "data" not in air_quality:
                return False

            try:
                aqi = air_quality["data"]["current"]["pollution"]["aqius"]
                actual_city = air_quality["data"]["city"]
            except KeyError:
                logger.error(f"❌ Unexpected air quality data structure for {city}")
                return False

            logger.info(f"📊 AQI for {actual_city}: {aqi}")

            message = self.get_aqi_message(actual_city, aqi)
            if message:
                success = self.send_whatsapp_message(phone_number, message)
                if success:
                    logger.info(f"✅ AQI alert sent to {name} ({city}): AQI {aqi}")
                return success
            else:
                logger.info(f"ℹ️ AQI {aqi} for {city} is safe, no message sent")
                return True

        except Exception as e:
            logger.error(f"❌ Error processing user {user.get('name', 'Unknown')}: {e}")
            return False

    def run_monitoring_cycle(self, spreadsheet_id: str, sheet_name: str = "Sheet1"):
        """Run monitoring cycle"""
        logger.info("🚀 Starting air quality monitoring cycle")

        try:
            users_data = self.get_google_sheets_data(spreadsheet_id, sheet_name)
            notification_users = self.filter_notification_enabled_users(users_data)

            success_count = 0
            for user in notification_users:
                if self.process_user(user):
                    success_count += 1
                time.sleep(1)

            logger.info(f"🎯 Monitoring cycle done. Processed {success_count}/{len(notification_users)} users")
        except Exception as e:
            logger.error(f"❌ Error in monitoring cycle: {e}")


def main():
    config = {
        "service_account_path": "service-account-key.json",
        "airvisual_api_key": os.environ["AIRVISUAL_API_KEY"],
        "ultramsg_token": os.environ["ULTRAMSG_TOKEN"],
        "ultramsg_instance": os.environ["ULTRAMSG_INSTANCE"],
    }
    spreadsheet_id = os.environ["SPREADSHEET_ID"]

    monitor = AirQualityMonitor(**config)
    monitor.run_monitoring_cycle(spreadsheet_id)


if __name__ == "__main__":
    main()
