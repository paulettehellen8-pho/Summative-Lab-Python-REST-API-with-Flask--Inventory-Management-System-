"""Tests for the API routes. OpenFoodFacts is always replaced by a fake,
so no test uses the internet.
"""

from unittest.mock import patch

import pytest

from app import app, inventory, Item
from external_api import ExternalAPIError, ProductNotFoundError

PRODUCT = {"barcode": "7340011364207", "product_name": "Oat Drink",
           "brands": "Oatly", "ingredients_text": "Water, oats"}
IMPORT_BODY = {"barcode": "7340011364207", "price": 2.5, "stock": 10}


@pytest.fixture(autouse=True)
def reset_inventory():
    # change the same list that app.py uses, so we clear and refill it
    inventory.clear()
    inventory.append(Item(1, "Almond Milk", 3.49, 40, barcode="0012345678905"))
    inventory.append(Item(2, "Hazelnut Spread", 4.99, 25,
                          barcode="3017620422003"))


@pytest.fixture
def client():
    return app.test_client()


# ---------- read ----------

def test_welcome(client):
    """GET / returns a welcome message."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.get_json()


def test_get_inventory(client):
    """GET /inventory returns every item."""
    response = client.get("/inventory")
    assert response.status_code == 200
    assert len(response.get_json()) == 2


def test_get_inventory_when_empty(client):
    """An empty inventory is an empty list, not an error."""
    inventory.clear()
    response = client.get("/inventory")
    assert response.status_code == 200
    assert response.get_json() == []


def test_get_item(client):
    """GET /inventory/<id> returns that item."""
    response = client.get("/inventory/2")
    assert response.status_code == 200
    assert response.get_json()["product_name"] == "Hazelnut Spread"


def test_get_item_not_found(client):
    """An id that does not exist gives 404 and names the id."""
    response = client.get("/inventory/99")
    assert response.status_code == 404
    assert "99" in response.get_json()["error"]


def test_unknown_url_returns_json_404(client):
    """A URL that does not exist gives a JSON 404, not an HTML page."""
    response = client.get("/inventory/abc")
    assert response.status_code == 404
    assert response.is_json


def test_wrong_method_returns_json_405(client):
    """A wrong method (PUT) gives a JSON 405."""
    response = client.put("/inventory/1", json={"price": 1})
    assert response.status_code == 405
    assert response.is_json


def test_crash_returns_json_500(client):
    """If the code crashes, the client still gets a JSON 500."""
    with patch("app.find_item", side_effect=RuntimeError("boom")):
        response = client.get("/inventory/1")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Internal server error"}


# ---------- create ----------

def test_create_item(client):
    """A valid POST creates the item with the next id."""
    response = client.post("/inventory", json={
        "product_name": "Oat Drink", "price": 2.5, "stock": 10,
        "barcode": "7340011364207"})
    assert response.status_code == 201
    assert response.get_json()["id"] == 3
    assert len(inventory) == 3


def test_create_item_without_barcode(client):
    """The barcode is optional."""
    response = client.post("/inventory", json={
        "product_name": "Apples", "price": 1, "stock": 5})
    assert response.status_code == 201
    assert response.get_json()["barcode"] is None


def test_create_item_trims_name(client):
    """Spaces around the name are removed."""
    response = client.post("/inventory", json={
        "product_name": "  Tea  ", "price": 1, "stock": 1})
    assert response.get_json()["product_name"] == "Tea"


def test_id_is_not_reused_after_delete(client):
    """After deleting item 1 the next id is 3, not 2 (2 still exists)."""
    client.delete("/inventory/1")
    response = client.post("/inventory", json={
        "product_name": "Tea", "price": 1, "stock": 1})
    assert response.get_json()["id"] == 3


def test_first_id_in_empty_inventory_is_1(client):
    """The first item in an empty inventory gets id 1."""
    inventory.clear()
    response = client.post("/inventory", json={
        "product_name": "Tea", "price": 1, "stock": 1})
    assert response.get_json()["id"] == 1


def test_create_duplicate_barcode(client):
    """A barcode that already exists gives 409 and adds nothing."""
    response = client.post("/inventory", json={
        "product_name": "Copy", "price": 1, "stock": 1,
        "barcode": "3017620422003"})
    assert response.status_code == 409
    assert len(inventory) == 2


@pytest.mark.parametrize("body, text", [
    ({"price": 1, "stock": 1}, "product_name"),
    ({"product_name": "A", "stock": 1}, "price"),
    ({"product_name": "A", "price": 1}, "stock"),
    ({"product_name": "   ", "price": 1, "stock": 1}, "empty"),
    ({"product_name": 5, "price": 1, "stock": 1}, "string"),
    ({"product_name": "A" * 101, "price": 1, "stock": 1}, "longer"),
    ({"product_name": "A", "price": "3", "stock": 1}, "number"),
    ({"product_name": "A", "price": True, "stock": 1}, "number"),
    ({"product_name": "A", "price": -1, "stock": 1}, "negative"),
    ({"product_name": "A", "price": 1.999, "stock": 1}, "2 decimal"),
    ({"product_name": "A", "price": 1e308, "stock": 1}, "more than"),
    ({"product_name": "A", "price": 1, "stock": 1.5}, "whole"),
    ({"product_name": "A", "price": 1, "stock": True}, "whole"),
    ({"product_name": "A", "price": 1, "stock": -3}, "negative"),
    ({"product_name": "A", "price": 1, "stock": 1, "barcode": 123}, "barcode"),
    ({"product_name": "A", "price": 1, "stock": 1, "barcode": "12ab"}, "barcode"),
    ({"product_name": "A", "price": 1, "stock": 1, "barcode": "123"}, "barcode"),
    ({"product_name": "A", "price": 1, "stock": 1, "id": 9}, "Unknown"),
    ({"product_name": "A", "price": 1, "stock": 1, "colour": "red"}, "Unknown"),
    ({}, "Missing"),
])
def test_create_invalid_input(client, body, text):
    """Every kind of bad input gives 400 and adds nothing."""
    response = client.post("/inventory", json=body)
    assert response.status_code == 400
    assert text in response.get_json()["error"]
    assert len(inventory) == 2  # nothing was added


def test_create_rejects_nan_price(client):
    """NaN is valid in Python's JSON but is not a price."""
    response = client.post(
        "/inventory", content_type="application/json",
        data='{"product_name": "A", "price": NaN, "stock": 1}')
    assert response.status_code == 400


@pytest.mark.parametrize("kwargs", [
    {"data": "{not json", "content_type": "application/json"},
    {"json": [1, 2]},
    {"json": "hello"},
])
def test_create_with_bad_body(client, kwargs):
    """Broken JSON or a body that is not an object gives 400."""
    response = client.post("/inventory", **kwargs)
    assert response.status_code == 400
    assert "JSON object" in response.get_json()["error"]


def test_create_without_json_content_type(client):
    """A body without the JSON Content-Type gives 415."""
    response = client.post("/inventory", data="hello")
    assert response.status_code == 415


# ---------- update ----------

def test_update_price_and_stock(client):
    """PATCH changes only the fields that were sent."""
    response = client.patch("/inventory/1", json={"price": 2.99, "stock": 35})
    assert response.status_code == 200
    data = response.get_json()
    assert data["price"] == 2.99
    assert data["stock"] == 35
    assert data["product_name"] == "Almond Milk"  # not changed


def test_update_stock_to_zero(client):
    """Zero is a valid stock (sold out), so it must be accepted."""
    response = client.patch("/inventory/1", json={"stock": 0})
    assert response.status_code == 200
    assert response.get_json()["stock"] == 0


def test_update_item_not_found(client):
    """PATCH on a missing item gives 404."""
    assert client.patch("/inventory/99", json={"stock": 1}).status_code == 404


def test_update_missing_item_beats_bad_body(client):
    """A missing item is 404 even when the body is also wrong."""
    response = client.patch("/inventory/99", json={"stock": "lots"})
    assert response.status_code == 404


@pytest.mark.parametrize("body, text", [
    ({}, "No fields"),
    ({"stock": -1}, "negative"),
    ({"price": "free"}, "number"),
    ({"barcode": "3017620422003"}, "non-editable"),
    ({"id": 5}, "non-editable"),
    ({"stok": 1}, "Unknown"),
])
def test_update_invalid_input(client, body, text):
    """Bad PATCH input gives 400 and the item stays the same."""
    response = client.patch("/inventory/1", json=body)
    assert response.status_code == 400
    assert text in response.get_json()["error"]
    assert inventory[0].stock == 40


def test_update_does_not_half_apply(client):
    """If one field is bad, none of the fields are changed."""
    # price is fine but stock is not, so nothing may change
    response = client.patch("/inventory/1", json={"price": 9.99, "stock": -1})
    assert response.status_code == 400
    assert inventory[0].price == 3.49


# ---------- delete ----------

def test_delete_item(client):
    """DELETE removes the item and gives 204."""
    response = client.delete("/inventory/2")
    assert response.status_code == 204
    assert len(inventory) == 1


def test_delete_item_not_found(client):
    """DELETE on a missing item gives 404."""
    assert client.delete("/inventory/99").status_code == 404
    assert len(inventory) == 2


# ---------- import ----------

def test_import_item(client):
    """Name and brands come from OpenFoodFacts, price and stock from the store."""
    with patch("app.fetch_product_by_barcode", return_value=PRODUCT) as fake:
        response = client.post("/inventory/import", json=IMPORT_BODY)
    assert response.status_code == 201
    data = response.get_json()
    assert data["product_name"] == "Oat Drink"  # from OpenFoodFacts
    assert data["price"] == 2.5                 # from the store
    assert data["stock"] == 10
    assert len(inventory) == 3
    fake.assert_called_once_with("7340011364207")


def test_import_store_name_wins(client):
    """A name sent by the store replaces the OpenFoodFacts name."""
    with patch("app.fetch_product_by_barcode", return_value=PRODUCT):
        response = client.post("/inventory/import",
                               json=dict(IMPORT_BODY, product_name="Mine"))
    assert response.get_json()["product_name"] == "Mine"


def test_import_product_without_name(client):
    """No name anywhere gives 400 and adds nothing."""
    nameless = dict(PRODUCT, product_name="")
    with patch("app.fetch_product_by_barcode", return_value=nameless):
        response = client.post("/inventory/import", json=IMPORT_BODY)
    assert response.status_code == 400
    assert len(inventory) == 2


def test_import_cuts_very_long_text(client):
    """Text that is too long is cut to the limit, not rejected."""
    long_product = dict(PRODUCT, ingredients_text="x" * 5000)
    with patch("app.fetch_product_by_barcode", return_value=long_product):
        response = client.post("/inventory/import", json=IMPORT_BODY)
    assert response.status_code == 201
    assert len(response.get_json()["ingredients_text"]) == 1000


def test_import_duplicate_does_not_call_external_api(client):
    """A duplicate is rejected before OpenFoodFacts is asked."""
    with patch("app.fetch_product_by_barcode") as fake:
        response = client.post("/inventory/import", json=dict(
            IMPORT_BODY, barcode="3017620422003"))
    assert response.status_code == 409
    fake.assert_not_called()


def test_import_product_not_found(client):
    """A barcode OpenFoodFacts does not know gives 404."""
    with patch("app.fetch_product_by_barcode",
               side_effect=ProductNotFoundError("not found")):
        response = client.post("/inventory/import", json=IMPORT_BODY)
    assert response.status_code == 404
    assert len(inventory) == 2


def test_import_external_api_down(client):
    """If OpenFoodFacts fails the API answers 502 and adds nothing."""
    with patch("app.fetch_product_by_barcode",
               side_effect=ExternalAPIError("Could not reach OpenFoodFacts")):
        response = client.post("/inventory/import", json=IMPORT_BODY)
    assert response.status_code == 502
    assert len(inventory) == 2


@pytest.mark.parametrize("body", [
    {"price": 1, "stock": 1},
    {"barcode": "7340011364207", "stock": 1},
    {"barcode": "7340011364207", "price": 1},
    {"barcode": "abc", "price": 1, "stock": 1},
    {"barcode": "7340011364207", "price": -1, "stock": 1},
    {"barcode": "7340011364207", "price": 1, "stock": 1, "brands": "X"},
])
def test_import_invalid_input(client, body):
    """Bad import input gives 400 and never calls OpenFoodFacts."""
    with patch("app.fetch_product_by_barcode") as fake:
        response = client.post("/inventory/import", json=body)
    assert response.status_code == 400
    fake.assert_not_called()


# ---------- lookup and search ----------

def test_lookup_barcode(client):
    """A lookup returns the product but does not save it."""
    with patch("app.fetch_product_by_barcode", return_value=PRODUCT):
        response = client.get("/products/barcode/7340011364207")
    assert response.status_code == 200
    assert response.get_json()["product_name"] == "Oat Drink"
    assert len(inventory) == 2  # lookup does not save anything


def test_lookup_invalid_barcode(client):
    """A bad barcode gives 400 without calling OpenFoodFacts."""
    with patch("app.fetch_product_by_barcode") as fake:
        response = client.get("/products/barcode/abc")
    assert response.status_code == 400
    fake.assert_not_called()


def test_lookup_not_found(client):
    """An unknown barcode gives 404."""
    with patch("app.fetch_product_by_barcode",
               side_effect=ProductNotFoundError("not found")):
        response = client.get("/products/barcode/7340011364207")
    assert response.status_code == 404


def test_lookup_external_api_down(client):
    """A failing OpenFoodFacts gives 502."""
    with patch("app.fetch_product_by_barcode",
               side_effect=ExternalAPIError("took too long")):
        response = client.get("/products/barcode/7340011364207")
    assert response.status_code == 502


def test_search_products(client):
    """A search returns the list from OpenFoodFacts."""
    with patch("app.search_products_by_name", return_value=[PRODUCT]) as fake:
        response = client.get("/products/search?name=oat")
    assert response.status_code == 200
    assert response.get_json() == [PRODUCT]
    fake.assert_called_once_with("oat")


def test_search_with_no_results(client):
    """No results is an empty list with status 200."""
    with patch("app.search_products_by_name", return_value=[]):
        response = client.get("/products/search?name=zzzz")
    assert response.status_code == 200
    assert response.get_json() == []


@pytest.mark.parametrize("url", [
    "/products/search",
    "/products/search?name=",
    "/products/search?name=%20%20",
    "/products/search?name=" + "a" * 101,
])
def test_search_invalid_name(client, url):
    """A missing, empty or too long name gives 400."""
    with patch("app.search_products_by_name") as fake:
        response = client.get(url)
    assert response.status_code == 400
    fake.assert_not_called()


def test_search_external_api_down(client):
    """A failing OpenFoodFacts gives 502."""
    with patch("app.search_products_by_name",
               side_effect=ExternalAPIError("Could not reach OpenFoodFacts")):
        response = client.get("/products/search?name=oat")
    assert response.status_code == 502