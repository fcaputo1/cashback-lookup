from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import urllib.request

BOARD_SLUG = "7CfN76Cf46duqFEhB6anMd"
BOARD_UUID = "3237a7f0-4e70-4b46-9e75-a8533d6f7d38"
MIXPANEL_URL = "https://mixpanel.com/api/app/public/dashboard-cards"
VERIFY_URL = f"https://mixpanel.com/api/app/public/verify/{BOARD_UUID}/"
BOOKMARK_IDS = [89622898, 89646604, 89646606, 89646770, 89646850, 89646869, 89646917, 89646931, 89646959]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

COUNTRY_NAMES = {
    "AR": "Argentina", "BO": "Bolivia", "CL": "Chile", "CO": "Colombia",
    "CR": "Costa Rica", "DO": "República Dominicana", "EC": "Ecuador",
    "GT": "Guatemala", "HN": "Honduras", "MX": "México", "NG": "Nigeria",
    "PA": "Panamá", "PE": "Perú", "PY": "Paraguay", "SV": "El Salvador",
    "UY": "Uruguay",
}


def get_auth_cookie():
    password = os.environ.get("MIXPANEL_PASSWORD", "").strip()
    body = json.dumps({"password": password}).encode()
    req = urllib.request.Request(VERIFY_URL, data=body, headers={
        "Content-Type": "application/json",
        "Origin": "https://mixpanel.com",
        "Referer": f"https://mixpanel.com/public/{BOARD_SLUG}",
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        cookies = [
            val.split(";")[0].strip()
            for name, val in resp.getheaders()
            if name.lower() == "set-cookie"
        ]
        return "; ".join(cookies)


def fetch_card(bid, auth_cookie):
    body = json.dumps({
        "uuid": BOARD_UUID,
        "bookmark_id": bid,
        "endpoint": "insights",
        "query_origin": "dashboard_public"
    }).encode()
    req = urllib.request.Request(MIXPANEL_URL, data=body, headers={
        "Content-Type": "application/json",
        "Origin": "https://mixpanel.com",
        "Referer": f"https://mixpanel.com/public/{BOARD_SLUG}",
        "User-Agent": UA,
        "Cookie": auth_cookie,
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    series = data["results"]["series"]["Uniques of Cashback Status Change"]
    return {k: v for k, v in series.items() if not k.startswith("$")}


def fetch_user(distinct_id):
    auth_cookie = get_auth_cookie()

    all_series = {}
    with ThreadPoolExecutor(max_workers=9) as ex:
        futures = {ex.submit(fetch_card, bid, auth_cookie): bid for bid in BOOKMARK_IDS}
        for f in as_completed(futures):
            all_series.update(f.result())

    user_data = all_series.get(distinct_id)
    if not user_data:
        return None, "not_found"

    country, cashback_current, actual_pct = "—", "—", "—"
    for k, v in user_data.items():
        if k.startswith("$"):
            continue
        country = k
        if not isinstance(v, dict):
            continue
        for cb, cb_val in v.items():
            if cb.startswith("$"):
                continue
            cashback_current = cb
            if isinstance(cb_val, dict):
                for pct in cb_val:
                    if not pct.startswith("$") and pct != "undefined":
                        actual_pct = pct
            break
        break

    return {
        "country": country,
        "country_name": COUNTRY_NAMES.get(country, country),
        "cashback_current": cashback_current,
        "actual_pct": actual_pct,
    }, None


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        uid = parse_qs(urlparse(self.path).query).get("id", [""])[0].strip()
        if not uid:
            self._json({"error": "missing_id"})
            return
        try:
            user, error = fetch_user(uid)
        except Exception as e:
            self._json({"error": str(e)})
            return

        if error == "not_found":
            self._json({"error": "not_found"})
        elif error:
            self._json({"error": error})
        else:
            self._json(user)

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
