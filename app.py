"""Inventory Management API.

A small Flask REST API that stores items in memory. Items can be added by
hand or imported from OpenFoodFacts using a barcode.
"""

from flask import Flask, jsonify, request

# The OpenFoodFacts client lives in external_api.py, together with the two
# custom errors it raises
from external_api import (ExternalAPIError, ProductNotFoundError,
                          fetch_product_by_barcode, search_products_by_name)

app = Flask(__name__)

# ---------- SETTINGS ----------
# Limits live here so we can change them in one place
MAX_NAME = 100
MAX_INGREDIENTS = 1000
MAX_PRICE = 999999999.99

# Which fields each kind of request is allowed to contain.
# Anything else is rejected, so a typo like "stok" is not silently ignored.
CREATE_FIELDS = {"barcode", "product_name", "brands", "ingredients_text",
                 "price", "stock"}
# barcode and id are missing here on purpose: they cannot be changed later
UPDATE_FIELDS = {"product_name", "brands", "ingredients_text", "price",
                 "stock"}
# For an import, OpenFoodFacts supplies the details. The store only
# supplies the price and stock (and optionally its own name).
IMPORT_FIELDS = {"barcode", "product_name", "price", "stock"}


# ---------- DATA ----------

class Item:
    """One product in the inventory."""

    def __init__(self, id, product_name, price, stock, barcode=None,
                 brands="", ingredients_text=""):
        self.id = id                # unique number made by the server
        self.barcode = barcode      # kept as text so leading zeros stay
        self.product_name = product_name
        self.brands = brands
        self.ingredients_text = ingredients_text
        self.price = price
        self.stock = stock

    def to_dict(self):
        """Turn the item into a dictionary, because jsonify needs one."""
        return {
            "id": self.id,
            "barcode": self.barcode,
            "product_name": self.product_name,
            "brands": self.brands,
            "ingredients_text": self.ingredients_text,
            "price": self.price,
            "stock": self.stock,
        }


# The in-memory "database": a list of Item objects.
# Nothing is saved to disk, so it resets when the server restarts.
inventory = [
    Item(1, "Organic Almond Milk", 3.49, 40, barcode="0012345678905",
         brands="Silk", ingredients_text="Water, almonds, sea salt"),
    Item(2, "Hazelnut Spread", 4.99, 25, barcode="3017620422003",
         brands="Nutella", ingredients_text="Sugar, palm oil, hazelnuts"),
    Item(3, "Cola Soft Drink", 1.99, 120, barcode="5449000000996",
         brands="Coca-Cola", ingredients_text="Water, sugar, colour"),
]


# ---------- HELPER FUNCTIONS ----------

def error(message, status):
    """Build an error reply in one format: {"error": "message"}."""
    return jsonify({"error": message}), status


def find_item(item_id):
    """Return the item with this id, or None if there is no such item."""
    for item in inventory:
        if item.id == item_id:
            return item
    return None  # the route decides what to do (it sends a 404)


def find_by_barcode(barcode):
    """Return the item with this barcode, or None."""
    for item in inventory:
        if item.barcode == barcode:
            return item
    return None


def next_id():
    """Return the next free id: the highest id + 1 (1 if the list is empty)."""
    # max + 1 and not len + 1, so an id is never reused after a delete.
    # default=0 stops max() from crashing on an empty list.
    return max((item.id for item in inventory), default=0) + 1


def check_text(name, value, max_length, can_be_empty=True):
    """Check a text value. Returns an error message, or None if it is fine."""
    if not isinstance(value, str):
        return f"{name} must be a string"
    value = value.strip()  # so "   " counts as empty
    if not value and not can_be_empty:
        return f"{name} cannot be empty"
    if len(value) > max_length:
        return f"{name} cannot be longer than {max_length} characters"
    return None


def check_field(name, value):
    """Check one field. Returns an error message, or None if it is fine."""
    if name == "product_name":
        return check_text(name, value, MAX_NAME, can_be_empty=False)
    if name == "brands":
        return check_text(name, value, MAX_NAME)
    if name == "ingredients_text":
        return check_text(name, value, MAX_INGREDIENTS)

    if name == "barcode":
        if not isinstance(value, str):
            return "barcode must be a string"
        # barcodes have 8 to 14 digits (EAN-8 up to GTIN-14)
        if not value.strip().isdigit() or not 8 <= len(value.strip()) <= 14:
            return "barcode must be 8 to 14 digits"

    if name == "price":
        # bool is a kind of int in Python, so True would pass without this check
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "price must be a number"
        if value != value:  # NaN is the only number that is not equal to itself
            return "price must be a real number"
        if value < 0:
            return "price cannot be negative"
        if value > MAX_PRICE:  # also catches Infinity and huge numbers
            return f"price cannot be more than {MAX_PRICE}"
        if round(value, 2) != value:  # money has at most 2 decimals
            return "price can have at most 2 decimal places"

    if name == "stock":
        if isinstance(value, bool) or not isinstance(value, int):
            return "stock must be a whole number"
        if value < 0:
            return "stock cannot be negative"

    return None


def get_data(allowed, required):
    """Read and check the JSON body of a request.

    allowed:  the field names the request may contain
    required: the field names that must be there (an empty set means the
              client only sends what it wants to change, like in PATCH)
    Returns (data, None) when the body is fine, or (None, error_reply).
    """
    # 415 = Unsupported Media Type: the client did not say it sends JSON
    if not request.is_json:
        return None, error("Content-Type must be application/json", 415)

    # silent=True gives None for broken JSON instead of an HTML error page
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, error("Request body must be a JSON object", 400)

    # reject unknown fields instead of ignoring them
    unknown = set(data) - allowed
    if unknown:
        return None, error(
            "Unknown or non-editable field(s): " + ", ".join(sorted(unknown)),
            400)

    missing = required - set(data)
    if missing:
        return None, error(
            "Missing field(s): " + ", ".join(sorted(missing)), 400)
    if not data:
        return None, error("No fields were sent", 400)

    # check every field BEFORE changing anything, so a bad request never
    # leaves an item half updated
    for name, value in data.items():
        problem = check_field(name, value)
        if problem:
            return None, error(problem, 400)
        if isinstance(value, str):
            data[name] = value.strip()  # remove spaces around the text
    return data, None


# ---------- ROUTES ----------

@app.route("/")
def home():
    """Welcome message."""
    return jsonify({"message": "Welcome to the Inventory Management API"})


@app.route("/inventory", methods=["GET"])
def get_inventory():
    """Return all items. An empty inventory gives [], which is not an error."""
    return jsonify([item.to_dict() for item in inventory])


# <int:item_id> only matches whole numbers, so /inventory/abc is a 404
@app.route("/inventory/<int:item_id>", methods=["GET"])
def get_item(item_id):
    """Return one item."""
    item = find_item(item_id)
    if item is None:
        return error(f"Item {item_id} not found", 404)
    return jsonify(item.to_dict())


@app.route("/inventory", methods=["POST"])
def create_item():
    """Add a new item. Needs product_name, price and stock."""
    data, problem = get_data(CREATE_FIELDS, {"product_name", "price", "stock"})
    if data is None:  # get_data gives None only when there is a problem
        return problem

    # two items may not share a barcode (409 = Conflict)
    barcode = data.get("barcode")
    if barcode is not None and find_by_barcode(barcode) is not None:
        return error(f"An item with barcode {barcode} already exists", 409)

    # **data turns the dict into keyword arguments for Item
    item = Item(next_id(), **data)
    inventory.append(item)  # change the list in place, never write inventory = ...
    return jsonify(item.to_dict()), 201  # 201 = Created


@app.route("/inventory/<int:item_id>", methods=["PATCH"])
def update_item(item_id):
    """Change some fields of an item. Only the fields that are sent change."""
    # look for the item first: a missing item is a 404 even if the body is bad
    item = find_item(item_id)
    if item is None:
        return error(f"Item {item_id} not found", 404)

    data, problem = get_data(UPDATE_FIELDS, set())
    if data is None:  # get_data gives None only when there is a problem
        return problem

    # setattr(item, "price", 5) does the same as item.price = 5,
    # but it works for any field name in data
    for field, value in data.items():
        setattr(item, field, value)
    return jsonify(item.to_dict())


@app.route("/inventory/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    """Delete an item."""
    item = find_item(item_id)
    if item is None:
        return error(f"Item {item_id} not found", 404)

    inventory.remove(item)
    return "", 204  # 204 = No Content: it worked, so there is nothing to send


@app.route("/inventory/import", methods=["POST"])
def import_item():
    """Add an item using the details from OpenFoodFacts.

    The store sends the barcode, price and stock. The name, brands and
    ingredients come from OpenFoodFacts.
    """
    data, problem = get_data(IMPORT_FIELDS, {"barcode", "price", "stock"})
    if data is None:  # get_data gives None only when there is a problem
        return problem

    # check for a duplicate BEFORE calling OpenFoodFacts, so we do not waste
    # a request on something we would reject anyway
    barcode = data["barcode"]
    if find_by_barcode(barcode) is not None:
        return error(f"An item with barcode {barcode} already exists", 409)

    try:
        product = fetch_product_by_barcode(barcode)
    except ProductNotFoundError as e:
        return error(str(e), 404)
    except ExternalAPIError as e:
        # 502 Bad Gateway: our server is fine, the other service failed
        return error(str(e), 502)

    # a name sent by the store is used instead of the OpenFoodFacts name
    name = data.get("product_name") or product["product_name"]
    if not name:
        return error("OpenFoodFacts has no name for this product, "
                     "please send product_name", 400)

    # [:MAX] cuts text that is too long. The text comes from another
    # website, so we shorten it instead of rejecting the import.
    item = Item(next_id(), name[:MAX_NAME], data["price"], data["stock"],
                barcode=barcode, brands=product["brands"][:MAX_NAME],
                ingredients_text=product["ingredients_text"][:MAX_INGREDIENTS])
    inventory.append(item)
    return jsonify(item.to_dict()), 201


@app.route("/products/barcode/<barcode>", methods=["GET"])
def lookup_barcode(barcode):
    """Look up a barcode on OpenFoodFacts. Does not change the inventory."""
    # the same barcode rule as the inventory routes
    problem = check_field("barcode", barcode)
    if problem:
        return error(problem, 400)

    try:
        product = fetch_product_by_barcode(barcode.strip())
    except ProductNotFoundError as e:
        return error(str(e), 404)
    except ExternalAPIError as e:
        return error(str(e), 502)
    return jsonify(product)


@app.route("/products/search", methods=["GET"])
def search_products():
    """Search OpenFoodFacts by name: /products/search?name=milk"""
    # a missing ?name= gives "", which check_text rejects as empty
    name = request.args.get("name", "")
    problem = check_text("name", name, MAX_NAME, can_be_empty=False)
    if problem:
        return error(problem, 400)

    try:
        products = search_products_by_name(name.strip())
    except ExternalAPIError as e:
        return error(str(e), 502)
    return jsonify(products)  # an empty list means no results, not an error


# ---------- ERROR HANDLER ----------

# Without this, Flask answers unknown URLs, wrong methods and crashes with
# an HTML page, and the CLI cannot read HTML as JSON.
@app.errorhandler(Exception)
def handle_error(e):
    """Turn every error into a JSON reply."""
    # 404, 405 and the other HTTP errors have a code and a description
    if hasattr(e, "code") and hasattr(e, "description"):
        return error(e.description, e.code)
    # anything else is a bug in our code: 500 = Internal Server Error
    return error("Internal server error", 500)


if __name__ == "__main__":
    app.run(debug=True)