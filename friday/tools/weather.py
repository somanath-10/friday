"""
Weather tools — fetch real-time weather data using Open-Meteo (free, no API key required).
"""

import httpx
from datetime import datetime


WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def register(mcp):

    @mcp.tool()
    async def get_weather(location: str) -> str:
        """
        Fetch the current weather and today's forecast for any city or location in the world.
        Use this whenever the user asks about weather, temperature, rain, conditions, etc.
        location: City name, e.g. 'Mumbai', 'London', 'New York', 'Bangalore', 'Tokyo'.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                # Step 1: Geocode the location name → lat/lon
                geo_url = "https://geocoding-api.open-meteo.com/v1/search"
                geo_resp = await client.get(geo_url, params={"name": location, "count": 1, "language": "en", "format": "json"})
                geo_data = geo_resp.json()

                results = geo_data.get("results", [])
                if not results:
                    return f"Could not find location: '{location}'. Try a more specific city name."

                place = results[0]
                lat = place["latitude"]
                lon = place["longitude"]
                city_name = place.get("name", location)
                country = place.get("country", "")
                admin1 = place.get("admin1", "")  # State/region

                # Step 2: Fetch weather for those coordinates
                weather_url = "https://api.open-meteo.com/v1/forecast"
                weather_params = {
                    "latitude": lat,
                    "longitude": lon,
                    "current": [
                        "temperature_2m",
                        "apparent_temperature",
                        "relative_humidity_2m",
                        "wind_speed_10m",
                        "wind_direction_10m",
                        "weathercode",
                        "precipitation",
                        "cloud_cover",
                    ],
                    "daily": [
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_sum",
                        "weathercode",
                        "sunrise",
                        "sunset",
                    ],
                    "timezone": "auto",
                    "forecast_days": 3,
                }

                weather_resp = await client.get(weather_url, params=weather_params)
                w = weather_resp.json()

                current = w.get("current", {})
                daily = w.get("daily", {})

                temp = current.get("temperature_2m", "?")
                feels_like = current.get("apparent_temperature", "?")
                humidity = current.get("relative_humidity_2m", "?")
                wind = current.get("wind_speed_10m", "?")
                code = current.get("weathercode", 0)
                precipitation = current.get("precipitation", 0)
                cloud = current.get("cloud_cover", "?")
                condition = WMO_CODES.get(code, f"Code {code}")

                location_str = city_name
                if admin1 and admin1 != city_name:
                    location_str += f", {admin1}"
                if country:
                    location_str += f", {country}"

                # Today's high/low
                today_max = daily.get("temperature_2m_max", [None])[0]
                today_min = daily.get("temperature_2m_min", [None])[0]
                sunrise = daily.get("sunrise", [None])[0]
                sunset = daily.get("sunset", [None])[0]

                # Format sunrise/sunset nicely
                def fmt_time(iso_str):
                    if not iso_str:
                        return "?"
                    try:
                        dt = datetime.fromisoformat(iso_str)
                        return dt.strftime("%I:%M %p")
                    except Exception:
                        return iso_str

                # Build next 3-day forecast
                forecast_lines = []
                dates = daily.get("time", [])
                max_temps = daily.get("temperature_2m_max", [])
                min_temps = daily.get("temperature_2m_min", [])
                daily_codes = daily.get("weathercode", [])
                daily_rain = daily.get("precipitation_sum", [])

                for i in range(min(3, len(dates))):
                    try:
                        date_dt = datetime.fromisoformat(dates[i])
                        label = date_dt.strftime("%A, %b %d")
                        cond = WMO_CODES.get(daily_codes[i] if i < len(daily_codes) else 0, "?")
                        hi = max_temps[i] if i < len(max_temps) else "?"
                        lo = min_temps[i] if i < len(min_temps) else "?"
                        rain = daily_rain[i] if i < len(daily_rain) else 0
                        rain_str = f" | Rain: {rain}mm" if rain and rain > 0.1 else ""
                        forecast_lines.append(f"  {label}: {cond} — High {hi}°C / Low {lo}°C{rain_str}")
                    except Exception:
                        break

                report = [
                    f"=== WEATHER: {location_str.upper()} ===",
                    f"Condition    : {condition}",
                    f"Temperature  : {temp}°C (feels like {feels_like}°C)",
                    f"Today H/L    : {today_max}°C / {today_min}°C",
                    f"Humidity     : {humidity}%",
                    f"Wind         : {wind} km/h",
                    f"Cloud Cover  : {cloud}%",
                ]
                if precipitation and float(precipitation) > 0.1:
                    report.append(f"Precipitation: {precipitation}mm")
                if sunrise and sunset:
                    report.append(f"Sunrise/Sunset: {fmt_time(sunrise)} / {fmt_time(sunset)}")
                if forecast_lines:
                    report.append("\n3-Day Forecast:")
                    report.extend(forecast_lines)

                return "\n".join(report)

        except Exception as e:
            return f"Error fetching weather: {str(e)}"
