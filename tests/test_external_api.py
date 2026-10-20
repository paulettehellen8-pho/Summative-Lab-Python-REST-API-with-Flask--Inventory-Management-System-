"""Tests for the OpenFoodFacts client. requests.get is replaced by a fake,
so no test uses the internet.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from external_api import (ExternalAPIError, ProductNotFoundError, as_text,
                          fetch_product_by_barcode, search_products_by_name)


def reply(status=200, data=None, bad_json=False):
    """A fake requests response, so no test uses the internet."""
    response = Mock(status_code=status)
    if bad_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = data
    return response


FOUND = {"status": 1, "product": {
    "code": "7340011364207", "product_name": " Oat Drink ",
    "brands": "Oatly", "ingredients_text": "Water, oats"}}


@pytest.mark.parametrize("value, expected", [
    ("  hi  ", "hi"), ("", ""), (None, ""), (5, ""), (["a"], ""),
])
def test_as_text(value, expected):
    """Text is trimmed and anything that is not text becomes an empty string."""
    assert as_text(value) == expected


# ---------- barcode lookup ----------

def test_fetch_product():
    """A found product is cleaned and returned."""
    with patch("external_api.requests.get", return_value=reply(200, FOUND)):
        product = fetch_product_by_barcode("7340011364207")
    assert product == {"barcode": "7340011364207", "product_name": "Oat Drink",
                       "brands": "Oatly", "ingredients_text": "Water, oats"}


def test_fetch_uses_timeout_and_user_agent():
    """The request must have a timeout and a User-Agent."""
    with patch("external_api.requests.get",
               return_value=reply(200, FOUND)) as get:
        fetch_product_by_barcode("7340011364207")
    assert get.call_args.args[0].endswith("/7340011364207.json")
    assert get.call_args.kwargs["timeout"] == 10
    assert "User-Agent" in get.call_args.kwargs["headers"]


@pytest.mark.parametrize("status, data", [
    (404, {"status": 0}),
    (200, {"status": 0}),
    (200, {"status": 1}),   # no product inside
])
def test_fetch_product_not_found(status, data):
    """HTTP 404, status 0 and a missing product all mean not found."""
    with patch("external_api.requests.get", return_value=reply(status, data)):
        with pytest.raises(ProductNotFoundError):
            fetch_product_by_barcode("7340011364207")


def test_fetch_fixes_missing_and_wrong_fields():
    """Missing or wrongly typed fields become empty strings."""
    data = {"status": 1, "product": {"product_name": 7, "brands": None}}
    with patch("external_api.requests.get", return_value=reply(200, data)):
        product = fetch_product_by_barcode("7340011364207")
    assert product["product_name"] == ""
    assert product["brands"] == ""


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_fetch_bad_status(status):
    """Any other HTTP status is an ExternalAPIError."""
    with patch("external_api.requests.get", return_value=reply(status, {})):
        with pytest.raises(ExternalAPIError):
            fetch_product_by_barcode("7340011364207")


def test_fetch_invalid_json():
    """A reply that is not JSON is an ExternalAPIError."""
    with patch("external_api.requests.get",
               return_value=reply(200, bad_json=True)):
        with pytest.raises(ExternalAPIError):
            fetch_product_by_barcode("7340011364207")


@pytest.mark.parametrize("data", [[], "text", 5, None])
def test_fetch_json_is_not_an_object(data):
    """JSON that is not an object is an ExternalAPIError."""
    with patch("external_api.requests.get", return_value=reply(200, data)):
        with pytest.raises(ExternalAPIError):
            fetch_product_by_barcode("7340011364207")


def test_fetch_timeout():
    """A timeout is an ExternalAPIError with a clear message."""
    with patch("external_api.requests.get", side_effect=requests.Timeout()):
        with pytest.raises(ExternalAPIError) as info:
            fetch_product_by_barcode("7340011364207")
    assert "too long" in str(info.value)


@pytest.mark.parametrize("error", [
    requests.ConnectionError(), requests.RequestException()])
def test_fetch_cannot_connect(error):
    """No connection is an ExternalAPIError with a clear message."""
    with patch("external_api.requests.get", side_effect=error):
        with pytest.raises(ExternalAPIError) as info:
            fetch_product_by_barcode("7340011364207")
    assert "Could not reach" in str(info.value)


# ---------- search ----------

def test_search_products():
    """A search returns cleaned products and sends the search words."""
    data = {"products": [{"code": "111", "product_name": "A"},
                         {"code": "222", "product_name": "B"}]}
    with patch("external_api.requests.get",
               return_value=reply(200, data)) as get:
        results = search_products_by_name("oat")
    assert [p["barcode"] for p in results] == ["111", "222"]
    assert get.call_args.kwargs["params"]["search_terms"] == "oat"


def test_search_no_results():
    """No results is an empty list, not an error."""
    with patch("external_api.requests.get",
               return_value=reply(200, {"products": []})):
        assert search_products_by_name("zzzz") == []


def test_search_skips_bad_records():
    """Records without a barcode, or that are not objects, are skipped."""
    data = {"products": [{"product_name": "no code"}, {"code": ""}, "junk",
                         None, {"code": "333", "product_name": "ok"}]}
    with patch("external_api.requests.get", return_value=reply(200, data)):
        results = search_products_by_name("x")
    assert [p["barcode"] for p in results] == ["333"]


@pytest.mark.parametrize("data", [{}, {"products": None}, [], "text"])
def test_search_unreadable_reply(data):
    """A reply without a products list is an ExternalAPIError."""
    with patch("external_api.requests.get", return_value=reply(200, data)):
        with pytest.raises(ExternalAPIError):
            search_products_by_name("x")


def test_search_bad_status():
    """A bad HTTP status is an ExternalAPIError."""
    with patch("external_api.requests.get", return_value=reply(500, {})):
        with pytest.raises(ExternalAPIError):
            search_products_by_name("x")


def test_search_timeout():
    """A timeout is an ExternalAPIError."""
    with patch("external_api.requests.get", side_effect=requests.Timeout()):
        with pytest.raises(ExternalAPIError):
            search_products_by_name("x")