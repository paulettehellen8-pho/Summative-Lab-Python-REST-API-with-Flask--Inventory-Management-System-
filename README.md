# Inventory Management System

A Flask REST API and a command-line tool for managing a shop's inventory.
Product details can be looked up on [OpenFoodFacts](https://world.openfoodfacts.org)
by barcode or name, and imported with the store's own price and stock.
The data is kept in memory, so it resets when the server restarts.

## Requirements

- Python 3.12
- pipenv
- Internet access (only for the OpenFoodFacts features)

## Installation

```bash
git clone <repository-url>
cd <project-folder>
pipenv install --dev
pipenv shell
```

## Start the API

```bash
python app.py
```

The API runs on http://127.0.0.1:5000. Keep this terminal open and use a
second terminal for the CLI.

## CLI

```bash
python cli.py list
python cli.py show 1
python cli.py add --name "Oat Drink" --price 2.50 --stock 10
python cli.py update 1 --price 2.99 --stock 35
python cli.py delete 1
python cli.py search "almond milk"
python cli.py barcode 3017620422003
python cli.py import 7340011364207 --price 2.50 --stock 10
```

`add` also accepts `--barcode`, `--brands` and `--ingredients`.
`import` accepts `--name` to replace the name from OpenFoodFacts.

To use another server address, use `--base-url http://host:port`
or set the `INVENTORY_API_URL` environment variable.

The CLI prints errors to the screen and exits with code 1 when something
goes wrong (server not running, timeout, invalid reply, or an error from the API).

## API endpoints

| Method | URL | Description | Success |
|--------|-----|-------------|---------|
| GET | `/` | Welcome message | 200 |
| GET | `/inventory` | List all items | 200 |
| GET | `/inventory/<id>` | Get one item | 200 |
| POST | `/inventory` | Add an item | 201 |
| PATCH | `/inventory/<id>` | Update an item | 200 |
| DELETE | `/inventory/<id>` | Delete an item | 204 |
| POST | `/inventory/import` | Add an item from OpenFoodFacts by barcode | 201 |
| GET | `/products/barcode/<barcode>` | Look up a barcode (does not save) | 200 |
| GET | `/products/search?name=...` | Search by name (does not save) | 200 |

Item fields: `id`, `barcode`, `product_name`, `brands`, `ingredients_text`, `price`, `stock`.

## Error handling

All errors are returned as JSON: `{"error": "message"}`.

| Status | Meaning |
|--------|---------|
| 400 | Invalid input: missing, unknown or wrongly typed fields, bad JSON |
| 404 | Item, URL or barcode not found |
| 405 | Method not allowed for this URL |
| 409 | An item with this barcode already exists |
| 415 | Body was not sent as `application/json` |
| 500 | Unexpected server error |
| 502 | OpenFoodFacts is unreachable, too slow or sent a bad reply |

Validation rules:

- `product_name` is required, must not be blank and has at most 100 characters.
- `price` is a number from 0 to 999999999.99 with at most 2 decimal places.
- `stock` is a whole number, 0 or more.
- `barcode` is text with 8 to 14 digits and must be unique.
- `id` and `barcode` cannot be changed with PATCH.
- A request with an invalid field changes nothing.

## Tests

```bash
python -m pytest
```

The tests replace OpenFoodFacts and the server with fakes, so they run
without internet. They cover normal use, invalid input, missing items,
duplicate barcodes, timeouts and broken replies.

## Project structure

```
app.py            API routes and validation
external_api.py   OpenFoodFacts client
cli.py            command-line tool
tests/            tests for the API, the client and the CLI
```