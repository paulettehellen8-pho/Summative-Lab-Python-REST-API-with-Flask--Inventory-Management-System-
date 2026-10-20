"""Client for the OpenFoodFacts website.

app.py uses the two functions at the bottom of this file. This file knows
nothing about Flask: it only talks to OpenFoodFacts and returns plain dicts.
That also makes it easy to test with fake replies.
"""

# requests is the library that sends HTTP requests to other websites
import requests

# ---------- SETTINGS ----------
BASE_URL = "https://world.openfoodfacts.org"
# OpenFoodFacts asks every app to say who it is with a User-Agent
HEADERS = {"User-Agent": "InventoryManagementLab/1.0 (student project)"}
# only ask for the fields we use, so the reply is small and fast
FIELDS = "code,product_name,brands,ingredients_text"
TIMEOUT = 10  # seconds. Without a timeout a slow server would freeze our API


# ---------- OUR OWN ERRORS ----------
# Two different error types let app.py answer differently:
# 404 (product does not exist) or 502 (the other service is broken).

class ExternalAPIError(Exception):
    """OpenFoodFacts could not be reached or sent a bad reply."""


class ProductNotFoundError(Exception):
    """OpenFoodFacts has no product with this barcode."""


# ---------- HELPER FUNCTIONS ----------

def as_text(value):
    """Return the value as trimmed text, or "" if it is not text."""
    # The data is written by the community, so a field can be missing
    # (None) or have an unexpected type. This keeps our data predictable.
    if isinstance(value, str):
        return value.strip()
    return ""


def clean_product(raw, barcode=None):
    """Turn a raw OpenFoodFacts product into the small dict our app uses."""
    return {
        # use the barcode we asked for, or the one inside the product
        "barcode": barcode or as_text(raw.get("code")),
        "product_name": as_text(raw.get("product_name")),
        "brands": as_text(raw.get("brands")),
        "ingredients_text": as_text(raw.get("ingredients_text")),
    }


def get_json(url, params):
    """Send a GET request. Returns (status_code, json or None).

    Raises ExternalAPIError if the website cannot be reached at all.
    """
    try:
        response = requests.get(url, params=params, headers=HEADERS,
                                timeout=TIMEOUT)
    except requests.Timeout:  # this must come BEFORE RequestException,
        # because Timeout is a kind of RequestException and would be caught there
        raise ExternalAPIError("OpenFoodFacts took too long to respond")
    except requests.RequestException:
        # no internet, DNS problem, connection refused, ...
        raise ExternalAPIError("Could not reach OpenFoodFacts")

    try:
        data = response.json()
    except ValueError:
        data = None  # the reply was not JSON (for example an HTML error page)
    return response.status_code, data


# ---------- FUNCTIONS USED BY app.py ----------

def fetch_product_by_barcode(barcode):
    """Look up one product by barcode.

    Returns a dict with barcode, product_name, brands and ingredients_text.
    Raises ProductNotFoundError if there is no such product, and
    ExternalAPIError if OpenFoodFacts fails.
    """
    url = f"{BASE_URL}/api/v2/product/{barcode}.json"
    status, data = get_json(url, {"fields": FIELDS})

    # OpenFoodFacts answers an unknown barcode with 404
    if status == 404:
        raise ProductNotFoundError(f"No product found for barcode {barcode}")
    if status != 200:
        raise ExternalAPIError(f"OpenFoodFacts returned status {status}")
    if not isinstance(data, dict):
        raise ExternalAPIError("OpenFoodFacts sent an unreadable reply")

    # "status" is 1 when the product was found and 0 when it was not
    product = data.get("product")
    if data.get("status") != 1 or not isinstance(product, dict):
        raise ProductNotFoundError(f"No product found for barcode {barcode}")
    return clean_product(product, barcode)


def search_products_by_name(name):
    """Search products by name. Returns a list of dicts (can be empty).

    Raises ExternalAPIError if OpenFoodFacts fails.
    """
    # The newer v2 API has no search by name, so this uses the older
    # search endpoint
    params = {"search_terms": name, "search_simple": 1, "action": "process",
              "json": 1, "page_size": 10, "fields": FIELDS}
    status, data = get_json(f"{BASE_URL}/cgi/search.pl", params)

    if status != 200:
        raise ExternalAPIError(f"OpenFoodFacts returned status {status}")
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise ExternalAPIError("OpenFoodFacts sent an unreadable reply")

    # skip records that are not objects or have no barcode, because we could
    # not import them. No results is fine: it gives an empty list.
    return [clean_product(p) for p in data["products"]
            if isinstance(p, dict) and as_text(p.get("code"))]