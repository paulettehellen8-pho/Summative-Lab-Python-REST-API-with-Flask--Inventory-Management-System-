"""Command line tool for the Inventory Management API.

The Flask server must be running first (python app.py). Examples:
    python cli.py list
    python cli.py add --name "Oat Drink" --price 2.50 --stock 10
    python cli.py import 7340011364207 --price 2.50 --stock 10

The CLI exits with code 0 when it worked and 1 when something went wrong.
"""

import argparse
import json
import os
import sys

import requests

# where the API runs by default (can be changed with --base-url)
DEFAULT_URL = "http://127.0.0.1:5000"


def build_parser():
    """Create the argument parser with one sub-command for each action."""
    parser = argparse.ArgumentParser(description="Inventory management CLI")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("INVENTORY_API_URL", DEFAULT_URL),
        help="address of the API (or set INVENTORY_API_URL)",
    )
    # every action is a sub-command: python cli.py <command> ...
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="show all items")

    show = commands.add_parser("show", help="show one item")
    show.add_argument("id", type=int)

    add = commands.add_parser("add", help="add an item")
    add.add_argument("--name", required=True)
    # type=float and type=int make argparse reject text like "abc" for us
    add.add_argument("--price", type=float, required=True)
    add.add_argument("--stock", type=int, required=True)
    add.add_argument("--barcode")
    add.add_argument("--brands")
    add.add_argument("--ingredients")

    update = commands.add_parser("update", help="change an item")
    update.add_argument("id", type=int)
    update.add_argument("--name")
    update.add_argument("--price", type=float)
    update.add_argument("--stock", type=int)
    update.add_argument("--brands")
    update.add_argument("--ingredients")

    delete = commands.add_parser("delete", help="delete an item")
    delete.add_argument("id", type=int)

    search = commands.add_parser("search", help="search OpenFoodFacts by name")
    search.add_argument("name")

    barcode = commands.add_parser("barcode", help="look up a barcode")
    barcode.add_argument("code")

    import_item = commands.add_parser("import", help="import by barcode")
    import_item.add_argument("barcode")
    import_item.add_argument("--price", type=float, required=True)
    import_item.add_argument("--stock", type=int, required=True)
    import_item.add_argument("--name")

    return parser


def pick(args, names):
    """Build a dict from the options the user actually typed.

    names is a list of (option name, API field name) pairs. Options the user
    left out are None, so they are not sent.
    """
    payload = {}
    for option, field in names:
        value = getattr(args, option)
        if value is not None:
            payload[field] = value
    return payload


def build_request(args, parser):
    """Return (method, path, payload, params) for the chosen command.

    payload is the JSON body and params are the ?query=values of the URL.
    """
    if args.command == "list":
        return "GET", "/inventory", None, None
    if args.command == "show":
        return "GET", f"/inventory/{args.id}", None, None
    if args.command == "add":
        payload = {"product_name": args.name, "price": args.price,
                   "stock": args.stock}
        payload.update(pick(args, [("barcode", "barcode"),
                                   ("brands", "brands"),
                                   ("ingredients", "ingredients_text")]))
        return "POST", "/inventory", payload, None
    if args.command == "update":
        payload = pick(args, [("name", "product_name"), ("price", "price"),
                              ("stock", "stock"), ("brands", "brands"),
                              ("ingredients", "ingredients_text")])
        # an update with nothing to change makes no sense, so stop early
        # (parser.error prints the message and exits with code 2)
        if not payload:
            parser.error("give at least one thing to change, "
                         "for example --price 2.50")
        return "PATCH", f"/inventory/{args.id}", payload, None
    if args.command == "delete":
        return "DELETE", f"/inventory/{args.id}", None, None
    if args.command == "search":
        return "GET", "/products/search", None, {"name": args.name}
    if args.command == "barcode":
        return "GET", f"/products/barcode/{args.code}", None, None

    # the only command left is "import"
    payload = {"barcode": args.barcode, "price": args.price,
               "stock": args.stock}
    payload.update(pick(args, [("name", "product_name")]))
    return "POST", "/inventory/import", payload, None


def main(argv=None):
    """Run the CLI. Returns the exit code, so tests can call it directly."""
    parser = build_parser()
    args = parser.parse_args(argv)
    method, path, payload, params = build_request(args, parser)
    # rstrip removes a "/" at the end, so we never build //inventory
    url = args.base_url.rstrip("/") + path

    try:
        response = requests.request(method, url, json=payload,
                                    params=params, timeout=20)
    # Timeout must come before ConnectionError and RequestException,
    # because both of them also match a timeout
    except requests.Timeout:
        print("Error: the server took too long to respond.", file=sys.stderr)
        return 1
    except requests.ConnectionError:
        print(f"Error: could not connect to {args.base_url}. "
              "Is the server running?", file=sys.stderr)
        return 1
    except requests.RequestException as error:
        print(f"Error: request failed: {error}", file=sys.stderr)
        return 1

    # 204 means "done, no body": the reply has no JSON to read (DELETE)
    if response.status_code == 204:
        print("Item deleted.")
        return 0

    # the server should always answer with JSON, but check in case it does not
    try:
        result = response.json()
    except ValueError:
        print(f"Error: the server sent invalid JSON "
              f"(status {response.status_code}).", file=sys.stderr)
        return 1

    # 400 and above are errors: show the message the API sent
    if response.status_code >= 400:
        message = result.get("error") if isinstance(result, dict) else None
        print(f"Error ({response.status_code}): "
              f"{message or 'request failed'}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))  # indent=2 makes it easy to read
    return 0


if __name__ == "__main__":
    sys.exit(main())