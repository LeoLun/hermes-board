"""天气：从 Open-Meteo 获取当前天气和未来三天预报（地理编码 + 预报接口，无需密钥）。

参数 city（可选）：先按新城市查找，成功后才保存为卡片的城市，避免输错城市名把卡片弄坏。
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card  # noqa: E402

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_CITY = "北京"
USER_AGENT = "hermes-board-weather/1.0"

# WMO 天气代码 → (中文描述, 图标类别)
WMO = {
    0: ("晴", "clear"), 1: ("大部晴朗", "clear"), 2: ("局部多云", "partly"), 3: ("阴", "cloudy"),
    45: ("雾", "fog"), 48: ("雾凇", "fog"),
    51: ("小毛毛雨", "rain"), 53: ("毛毛雨", "rain"), 55: ("大毛毛雨", "rain"),
    56: ("冻毛毛雨", "rain"), 57: ("冻毛毛雨", "rain"),
    61: ("小雨", "rain"), 63: ("中雨", "rain"), 65: ("大雨", "rain"), 66: ("冻雨", "rain"), 67: ("冻雨", "rain"),
    71: ("小雪", "snow"), 73: ("中雪", "snow"), 75: ("大雪", "snow"), 77: ("雪粒", "snow"),
    80: ("阵雨", "rain"), 81: ("阵雨", "rain"), 82: ("强阵雨", "rain"), 85: ("阵雪", "snow"), 86: ("强阵雪", "snow"),
    95: ("雷阵雨", "thunder"), 96: ("雷阵雨伴冰雹", "thunder"), 99: ("强雷阵雨伴冰雹", "thunder"),
}


def http_get_json(url, timeout=15):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def describe(code):
    text, kind = WMO.get(int(code) if code is not None else -1, ("未知", "cloudy"))
    return text, kind


def geocode(name, http_get):
    query = urllib.parse.urlencode({"name": name, "count": 1, "language": "zh", "format": "json"})
    results = (http_get(f"{GEOCODE_URL}?{query}") or {}).get("results") or []
    if not results:
        return None
    top = results[0]
    return {
        "name": top.get("name") or name,
        "latitude": float(top["latitude"]),
        "longitude": float(top["longitude"]),
        "timezone": top.get("timezone") or "auto",
        "admin1": top.get("admin1") or "",
        "country": top.get("country") or "",
    }


def forecast(place, http_get):
    query = urllib.parse.urlencode({
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": place["timezone"],
        "forecast_days": 4,
        "wind_speed_unit": "kmh",
    })
    return http_get(f"{FORECAST_URL}?{query}")


def _num(value, digits=1):
    return None if value is None else round(float(value), digits)


def build(place, raw):
    cur = raw["current"]
    daily = raw["daily"]
    days = []
    for i, date in enumerate(daily["time"][:4]):
        text, kind = describe(daily["weather_code"][i])
        pops = daily.get("precipitation_probability_max") or []
        days.append({
            "date": date,
            "code": daily["weather_code"][i],
            "text": text,
            "kind": kind,
            "max": _num(daily["temperature_2m_max"][i]),
            "min": _num(daily["temperature_2m_min"][i]),
            "pop": pops[i] if i < len(pops) else None,
        })
    text, kind = describe(cur.get("weather_code"))
    today = days[0] if days else {}
    current = {
        "city": place["name"],
        "region": place["admin1"],
        "temp": _num(cur.get("temperature_2m")),
        "feelsLike": _num(cur.get("apparent_temperature")),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": _num(cur.get("wind_speed_10m")),
        "code": cur.get("weather_code"),
        "text": text,
        "kind": kind,
        "isDay": bool(cur.get("is_day", 1)),
        "high": today.get("max"),
        "low": today.get("min"),
        "observedAt": cur.get("time"),
    }
    return current, days[1:4]


def main(card=None, http_get=http_get_json):
    card = card or Card()
    requested = str(card.args.get("city") or "").strip()
    city = requested or card.state.get("city") or DEFAULT_CITY

    card.progress(0.1, f"查找 {city}")
    try:
        place = geocode(city, http_get)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        card.fail(f"获取城市信息失败：{exc}")
    if place is None:
        card.fail(f"找不到城市“{city}”，换个写法试试，比如“上海”或“Shanghai”")

    card.progress(0.5, f"获取 {place['name']} 的天气")
    try:
        current, days = build(place, forecast(place, http_get))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        card.fail(f"获取天气失败：{exc}")

    if requested:
        card.state.set("city", place["name"])
    card.data.set("current", current)
    card.data.set("forecast", days)
    if current["temp"] is not None:
        card.series.append("temp", current["temp"])
    card.result({"city": place["name"], "temp": current["temp"], "text": current["text"]})


if __name__ == "__main__":
    main()
