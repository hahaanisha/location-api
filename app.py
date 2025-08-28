from flask import Flask, request, jsonify
import gspread
from google.oauth2 import service_account
import os
import json
import re
import math
from urllib.parse import unquote

app = Flask(__name__)

# Google Sheets setup - Works both locally and on Render
try:
    # ✅ Load credentials from environment variable
    creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

    if not creds_json:
        raise Exception("❌ GOOGLE_APPLICATION_CREDENTIALS_JSON not found in environment variables")

    # Parse JSON string into dict
    creds_dict = json.loads(creds_json)

    # Authenticate with Google
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    print("✅ Google Sheets connected successfully!")

except Exception as e:
    print(f"❌ Error connecting to Google Sheets: {str(e)}")
    raise


# Replace with your actual spreadsheet ID
SPREADSHEET_ID = "17cOylW-cc5fKKzHhyknUqwJCOuhwEJkjifVyh8WN5l8"
SHEET_NAME = "Location"

def extract_coordinates_from_url(url):
    """Extract latitude and longitude from various Google Maps URL formats"""
    try:
        url = unquote(url)
        print(f"Debug - Processing URL: {url}")

        if 'pb=' in url:
            pb_match = re.search(r'pb=([^&]+)', url)
            if pb_match:
                pb_data = unquote(pb_match.group(1))
                coord_patterns = [
                    r'!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)',
                    r'3d(-?\d+\.?\d*).*?4d(-?\d+\.?\d*)',
                    r'!2d(-?\d+\.?\d*)!3d(-?\d+\.?\d*)',
                ]
                for pattern in coord_patterns:
                    coord_match = re.search(pattern, pb_data)
                    if coord_match:
                        lat = float(coord_match.group(1))
                        lng = float(coord_match.group(2))
                        return lat, lng

        at_pattern = r'@(-?\d+\.?\d*),(-?\d+\.?\d*)'
        at_match = re.search(at_pattern, url)
        if at_match:
            lat = float(at_match.group(1))
            lng = float(at_match.group(2))
            return lat, lng

        direct_patterns = [
            r'(-?\d+\.?\d+),(-?\d+\.?\d+)',
            r'll=(-?\d+\.?\d*),(-?\d+\.?\d*)',
            r'center=(-?\d+\.?\d*),(-?\d+\.?\d*)',
        ]
        for pattern in direct_patterns:
            match = re.search(pattern, url)
            if match:
                lat = float(match.group(1))
                lng = float(match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    return lat, lng

        return None, None
    except Exception:
        return None, None

def haversine_distance(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return 6371 * c  # km

def find_nearest_station(user_lat, user_lng, stations_data):
    min_distance = float('inf')
    nearest_station = None
    for station in stations_data:
        try:
            station_lat = float(station['Latitude'])
            station_lng = float(station['Longitude'])
            distance = haversine_distance(user_lat, user_lng, station_lat, station_lng)
            if distance < min_distance:
                min_distance = distance
                nearest_station = {
                    'station': station['Station'],
                    'latitude': station_lat,
                    'longitude': station_lng,
                    'url': station['URL'],
                    'distance_km': round(distance, 2)
                }
        except (ValueError, KeyError):
            continue
    return nearest_station

@app.route("/debug_url", methods=["GET"])
def debug_url():
    maps_url = request.args.get("url")
    if not maps_url:
        return jsonify({"error": "Please provide a URL parameter"}), 400
    user_lat, user_lng = extract_coordinates_from_url(maps_url)
    return jsonify({
        "input_url": maps_url,
        "decoded_url": unquote(maps_url),
        "extracted_latitude": user_lat,
        "extracted_longitude": user_lng,
        "success": user_lat is not None and user_lng is not None
    })

@app.route("/nearest_station", methods=["GET"])
def nearest_station():
    lat_param = request.args.get("lat")
    lng_param = request.args.get("lng")
    if not lat_param or not lng_param:
        return jsonify({"error": "Please provide both 'lat' and 'lng' parameters"}), 400
    try:
        user_lat = float(lat_param)
        user_lng = float(lng_param)
        if not (-90 <= user_lat <= 90) or not (-180 <= user_lng <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400
    except ValueError:
        return jsonify({"error": "Invalid coordinate format"}), 400

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(SHEET_NAME)
        data = sheet.get_all_records()
        if not data:
            return jsonify({"error": "No station data found"}), 404
        nearest = find_nearest_station(user_lat, user_lng, data)
        if not nearest:
            return jsonify({"error": "Could not find any valid stations"}), 404
        return jsonify(nearest)
    except Exception as e:
        return jsonify({"error": f"Could not access sheet data: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "message": "Nearest Station API is running"})

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Nearest Station API",
        "usage": "GET /nearest_station?lat=LATITUDE&lng=LONGITUDE",
        "example": "GET /nearest_station?lat=19.086832&lng=72.905479",
        "parameters": {"lat": "Latitude", "lng": "Longitude"},
        "health_check": "GET /health"
    })

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
