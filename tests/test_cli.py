"""Tests for the command line tool. requests.request is replaced by a fake,
so no server is needed.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from cli import main


def reply(status=200, data=None, bad_json=False):
    response = Mock(status_code=status)
    if bad_json:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = data
    return response


@pytest.fixture(autouse=True)
def default_url(monkeypatch):
    monkeypatch.delenv("INVENTORY_API_URL", raising=False)


@pytest.mark.parametrize("argv, method, path, payload, params", [
    (["list"], "GET", "/inventory", None, None),
    (["show", "1"], "GET", "/inventory/1", None, None),
    (["add", "--name", "Milk", "--price", "2.5", "--stock", "10"],
     "POST", "/inventory",
     {"product_name": "Milk", "price": 2.5, "stock": 10}, None),
    (["add", "--name", "Milk", "--price", "2", "--stock", "1",
      "--barcode", "12345678", "--brands", "B", "--ingredients", "milk"],
     "POST", "/inventory",
     {"product_name": "Milk", "price": 2.0, "stock": 1,
      "barcode": "12345678", "brands": "B", "ingredients_text": "milk"}, None),
    (["update", "1", "--price", "9.99"],
     "PATCH", "/inventory/1", {"price": 9.99}, None),
    (["update", "1", "--stock", "0"],
     "PATCH", "/inventory/1", {"stock": 0}, None),
    (["delete", "1"], "DELETE", "/inventory/1", None, None),
    (["search", "almond milk"],
     "GET", "/products/search", None, {"name": "almond milk"}),
    (["barcode", "12345678"],
     "GET", "/products/barcode/12345678", None, None),
    (["import", "12345678", "--price", "2.5", "--stock", "10"],
     "POST", "/inventory/import",
     {"barcode": "12345678", "price": 2.5, "stock": 10}, None),
    (["import", "12345678", "--price", "2.5", "--stock", "10", "--name", "X"],
     "POST", "/inventory/import",
     {"barcode": "12345678", "price": 2.5, "stock": 10,
      "product_name": "X"}, None),
])
def test_commands_send_the_right_request(argv, method, path, payload, params):
    """Each command sends the right method, URL, body and parameters."""
    with patch("cli.requests.request",
               return_value=reply(200, {"ok": True})) as fake:
        assert main(argv) == 0
    fake.assert_called_once_with(method, "http://127.0.0.1:5000" + path,
                                 json=payload, params=params, timeout=20)


def test_prints_the_result(capsys):
    """The reply from the API is printed."""
    with patch("cli.requests.request",
               return_value=reply(200, [{"id": 1, "product_name": "Milk"}])):
        main(["list"])
    assert "Milk" in capsys.readouterr().out


def test_delete_has_no_body(capsys):
    """DELETE answers 204 with no JSON, which must not crash the CLI."""
    with patch("cli.requests.request", return_value=reply(204)):
        assert main(["delete", "1"]) == 0
    assert "deleted" in capsys.readouterr().out


def test_base_url_option_and_trailing_slash():
    """--base-url is used, and a / at the end is removed."""
    with patch("cli.requests.request", return_value=reply(200, [])) as fake:
        main(["--base-url", "http://example.com:8000/", "list"])
    assert fake.call_args.args[1] == "http://example.com:8000/inventory"


def test_base_url_from_environment(monkeypatch):
    """INVENTORY_API_URL is used when --base-url is not given."""
    monkeypatch.setenv("INVENTORY_API_URL", "http://env-host:1234")
    with patch("cli.requests.request", return_value=reply(200, [])) as fake:
        main(["list"])
    assert fake.call_args.args[1] == "http://env-host:1234/inventory"


# ---------- errors ----------

def test_api_error_is_shown(capsys):
    """The error message from the API is shown and the exit code is 1."""
    with patch("cli.requests.request",
               return_value=reply(404, {"error": "Item 99 not found"})):
        assert main(["show", "99"]) == 1
    assert "Item 99 not found" in capsys.readouterr().err


def test_error_reply_without_message(capsys):
    """An error reply without a message still gives a clear error."""
    with patch("cli.requests.request", return_value=reply(500, ["odd"])):
        assert main(["list"]) == 1
    assert "500" in capsys.readouterr().err


def test_invalid_json_reply(capsys):
    """A reply that is not JSON gives a clear error."""
    with patch("cli.requests.request",
               return_value=reply(502, bad_json=True)):
        assert main(["list"]) == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_server_not_running(capsys):
    """If the server is not running the user is told so."""
    with patch("cli.requests.request", side_effect=requests.ConnectionError()):
        assert main(["list"]) == 1
    assert "Is the server running" in capsys.readouterr().err


def test_timeout(capsys):
    """A slow server gives a clear error."""
    with patch("cli.requests.request", side_effect=requests.Timeout()):
        assert main(["list"]) == 1
    assert "too long" in capsys.readouterr().err


def test_other_request_error(capsys):
    """Any other request problem gives a clear error."""
    with patch("cli.requests.request",
               side_effect=requests.RequestException("bad")):
        assert main(["list"]) == 1
    assert "request failed" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    [],
    ["unknown"],
    ["show"],
    ["show", "abc"],
    ["add", "--price", "1", "--stock", "1"],
    ["add", "--name", "A", "--price", "abc", "--stock", "1"],
    ["add", "--name", "A", "--price", "1", "--stock", "1.5"],
    ["update", "1"],
    ["import", "12345678", "--price", "1"],
])
def test_bad_input_stops_before_calling_the_api(argv):
    """Bad arguments exit with code 2 and never call the API."""
    with patch("cli.requests.request") as fake:
        with pytest.raises(SystemExit) as info:
            main(argv)
    assert info.value.code == 2
    fake.assert_not_called()