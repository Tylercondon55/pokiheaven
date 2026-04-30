import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.robotparser import RobotFileParser

import stock_alert


class StockAlertTests(unittest.TestCase):
    def test_load_config_requires_safe_interval(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(
                """
                {
                  "check_interval_seconds": 10,
                  "products": [
                    {
                      "name": "Example",
                      "url": "https://example.com/card",
                      "in_stock_markers": ["add to cart"]
                    }
                  ]
                }
                """
            )
            config_path = Path(handle.name)

        try:
            with self.assertRaises(stock_alert.ConfigurationError):
                stock_alert.load_config(config_path)
        finally:
            config_path.unlink(missing_ok=True)

    def test_out_of_stock_marker_takes_precedence(self) -> None:
        product = stock_alert.Product(
            name="Booster Box",
            url="https://example.com/booster",
            in_stock_markers=("add to cart",),
            out_of_stock_markers=("sold out",),
        )
        result = stock_alert.FetchResult(
            url=product.url,
            status_code=200,
            body="Sold out. Add to cart button hidden.",
        )

        self.assertFalse(stock_alert.is_in_stock(product, result))

    def test_anti_abuse_marker_stops_monitor(self) -> None:
        product = stock_alert.Product(
            name="Elite Trainer Box",
            url="https://example.com/etb",
            in_stock_markers=("add to cart",),
        )
        result = stock_alert.FetchResult(
            url=product.url,
            status_code=200,
            body="Please verify you are human before continuing.",
        )

        with self.assertRaises(stock_alert.AntiAbuseSignal):
            stock_alert.ensure_no_anti_abuse_signal(product, result)

    @patch("stock_alert.urllib.request.urlopen")
    def test_http_429_stops_instead_of_retrying_or_bypassing(self, urlopen: Mock) -> None:
        product = stock_alert.Product(
            name="Pokemon Center ETB",
            url="https://example.com/product",
            in_stock_markers=("add to cart",),
        )
        urlopen.side_effect = stock_alert.urllib.error.HTTPError(
            product.url,
            429,
            "Too Many Requests",
            hdrs=None,
            fp=None,
        )

        with self.assertRaises(stock_alert.AntiAbuseSignal):
            stock_alert.fetch_product(product, "UnitTestAgent/1.0")

    def test_robots_txt_disallow_blocks_product_before_fetch(self) -> None:
        product = stock_alert.Product(
            name="Walmart search results",
            url="https://www.walmart.com/search?q=pokemon%20cards",
            in_stock_markers=("add to cart",),
        )
        parser = RobotFileParser()
        parser.parse(
            [
                "User-agent: *",
                "Disallow: /search",
                "Disallow: /api/",
                "Disallow: /feeds/*",
            ]
        )
        parser_cache = {stock_alert.robots_url_for(product.url): parser}

        with self.assertRaises(stock_alert.ConfigurationError):
            stock_alert.ensure_robots_allowed(product, "UnitTestAgent/1.0", parser_cache)

    def test_robots_txt_allows_non_disallowed_product_path(self) -> None:
        product = stock_alert.Product(
            name="Allowed product page",
            url="https://www.walmart.com/ip/example-product/123",
            in_stock_markers=("add to cart",),
        )
        parser = RobotFileParser()
        parser.parse(
            [
                "User-agent: *",
                "Disallow: /search",
                "Disallow: /api/",
                "Disallow: /feeds/*",
            ]
        )
        parser_cache = {stock_alert.robots_url_for(product.url): parser}

        stock_alert.ensure_robots_allowed(product, "UnitTestAgent/1.0", parser_cache)


if __name__ == "__main__":
    unittest.main()
