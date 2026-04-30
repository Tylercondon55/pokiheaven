# pokiheaven

A compliant Pokemon card stock alert tool.

This project monitors configured product pages and notifies you when configured
"in stock" text appears. It does **not** automate checkout, solve challenges,
rotate identities, or bypass retailer anti-bot controls.

## Safety defaults

- Uses a clear, configurable `User-Agent`.
- Enforces a minimum polling interval of 60 seconds.
- Checks each site's `robots.txt` before fetching a configured product URL.
- Stops when a retailer returns `401`, `403`, `407`, or `429`.
- Stops when a page appears to contain CAPTCHA or anti-abuse challenge text.
- Sends manual product links only; purchasing stays human-driven.

Before monitoring any retailer, review its terms and `robots.txt`. Prefer
official APIs, feeds, or retailer-provided alert options when available.

For example, Walmart publishes rules at
<https://www.walmart.com/robots.txt>. At the time this was referenced, Walmart
disallowed paths such as `/search`, `/api/`, `/feeds/*`, and several logger,
tracking, and store AJAX endpoints. Do not configure monitored URLs on
disallowed paths; choose an allowed public product page or use an official
retailer-provided alert/feed instead.

## Usage

Copy the sample config and edit it for product pages you are allowed to monitor:

```bash
cp products.example.json products.json
python3 stock_alert.py --config products.json --once
```

Run continuously:

```bash
python3 stock_alert.py --config products.json
```

The tool prints alerts to the console by default. To send email, fill in the
optional `email` block in `products.example.json`.

## Configuration

Each product needs:

- `name`: Friendly product name.
- `url`: Product page URL.
- `in_stock_markers`: Lowercase text snippets that appear when the product is
  available.
- `out_of_stock_markers`: Optional text snippets that should suppress alerts.

Top-level options include:

- `respect_robots_txt`: Defaults to `true`. Keep this enabled unless you have a
  written, explicit permission path that supersedes public robots.txt rules.

Choose stable markers from the page content, such as "add to cart" or "sold
out". If both out-of-stock and in-stock markers are present, the tool treats the
product as out of stock to avoid noisy alerts.

## Tests

```bash
python3 -m unittest
```
