"""Weather query tool using Open-Meteo API."""

import requests

from .base import Tool


class WeatherTool(Tool):
    """Tool for querying current weather information."""

    @property
    def name(self) -> str:
        return "weather_query"

    @property
    def description(self) -> str:
        return (
            "Query current weather for a city. "
            'Input: {"city": "city name"}. '
            "Returns temperature and weather condition summary."
        )

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Query current weather information for a city. Returns temperature in Celsius and weather condition.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name in Chinese or English, e.g. 'Beijing', 'Shanghai', '北京'"
                        }
                    },
                    "required": ["city"]
                }
            }
        }

    def run(self, params: dict) -> dict:
        city = params.get("city", "")
        if not city:
            return {
                "status": "error",
                "result": None,
                "message": "No city provided.",
            }

        try:
            result = self._query_weather(city)
            return {
                "status": "success",
                "result": result,
                "message": f"Current weather in {city}: {result['temperature']}°C, {result['weather']}",
            }
        except Exception as e:
            return {
                "status": "error",
                "result": None,
                "message": f"Weather query error: {str(e)}",
            }

    def _query_weather(self, city: str) -> dict:
        """Query weather using Open-Meteo geocoding + weather API."""
        # Step 1: Geocode city name
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_resp = requests.get(
            geo_url,
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=15,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()

        results = geo_data.get("results", [])
        if not results:
            raise ValueError(f"City '{city}' not found.")

        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        city_name = results[0].get("name", city)

        # Step 2: Get weather
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_resp = requests.get(
            weather_url,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code",
                "timezone": "auto",
            },
            timeout=15,
        )
        weather_resp.raise_for_status()
        weather_data = weather_resp.json()

        current = weather_data.get("current", {})
        temp = current.get("temperature_2m", "N/A")
        code = current.get("weather_code", -1)
        weather_desc = self._weather_code_to_desc(code)

        return {
            "city": city_name,
            "temperature": temp,
            "weather": weather_desc,
            "unit": "°C",
        }

    def _weather_code_to_desc(self, code: int) -> str:
        """Convert WMO weather code to description."""
        codes = {
            0: "Clear sky",
            1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            56: "Light freezing drizzle", 57: "Dense freezing drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            66: "Light freezing rain", 67: "Heavy freezing rain",
            71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
            77: "Snow grains",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            85: "Slight snow showers", 86: "Heavy snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
        }
        return codes.get(code, "Unknown")
