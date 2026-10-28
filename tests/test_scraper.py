import unittest
from unittest.mock import patch

import requests

from app.scraper import scrape_books


def make_response(url: str, html: str):
    class Response:
        content = html.encode("utf-8")
        status_code = 200

        def __init__(self) -> None:
            self.url = url

        @staticmethod
        def raise_for_status() -> None:
            return None

    return Response()


class ScrapeBooksTests(unittest.TestCase):
    @patch("app.scraper.time.sleep")
    @patch("app.scraper.requests.get")
    def test_extracts_book_data_and_follows_pagination(self, get, sleep):
        first_page = """
        <article class="product_pod">
          <h3><a href="book-one_1/index.html" title="Book One">Book One</a></h3>
          <div class="image_container"><img src="../../media/cache/cover-one.jpg" alt="Book One"></div>
          <p class="price_color">£12.50</p>
          <p class="availability">In stock</p>
          <p class="star-rating Three"></p>
        </article>
        <li class="next"><a href="page-2.html">next</a></li>
        """
        second_page = """
        <article class="product_pod">
          <h3><a href="book-two_2/index.html" title="Book Two">Book Two</a></h3>
          <p class="price_color">£8.99</p>
          <p class="availability">In stock</p>
          <p class="star-rating Five"></p>
        </article>
        """
        get.side_effect = [
            make_response(
                "https://books.toscrape.com/catalogue/page-1.html",
                first_page,
            ),
            make_response(
                "https://books.toscrape.com/catalogue/page-2.html",
                second_page,
            ),
        ]

        books = scrape_books(limit=2)

        self.assertEqual(len(books), 2)
        self.assertEqual(books[0]["title"], "Book One")
        self.assertEqual(books[0]["price"], 12.5)
        self.assertEqual(books[0]["rating"], "Three")
        self.assertEqual(
            books[0]["url"],
            "https://books.toscrape.com/catalogue/book-one_1/index.html",
        )
        self.assertEqual(
            books[0]["image_url"],
            "https://books.toscrape.com/media/cache/cover-one.jpg",
        )
        self.assertEqual(books[1]["title"], "Book Two")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once()

    @patch("app.scraper.requests.get")
    def test_skips_card_with_invalid_price(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="book_1/index.html" title="Book">Book</a></h3>
          <p class="price_color">not a price</p>
        </article>
        """
        get.return_value = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            html,
        )

        self.assertEqual(scrape_books(), [])

    @patch("app.scraper.requests.get")
    def test_skips_non_finite_price(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="book_1/index.html" title="Book">Book</a></h3>
          <p class="price_color">£NaN</p>
        </article>
        """
        get.return_value = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            html,
        )
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_handles_missing_optional_elements(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="book_1/index.html">Book</a></h3>
          <p class="price_color">£51.77</p>
        </article>
        """
        get.return_value = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            html,
        )

        books = scrape_books(limit=1)

        self.assertEqual(books[0]["title"], "Book")
        self.assertEqual(books[0]["price"], 51.77)
        self.assertEqual(books[0]["availability"], "Unknown")
        self.assertEqual(books[0]["rating"], "Unknown")
        self.assertIsNone(books[0]["image_url"])

    @patch("app.scraper.requests.get", side_effect=requests.Timeout("timed out"))
    def test_propagates_request_errors_for_api_handling(self, get):
        with self.assertRaises(requests.Timeout):
            scrape_books(limit=1)

    @patch("app.scraper.requests.get")
    def test_malformed_html_returns_empty_results(self, get):
        get.return_value = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            "<html><body>Unexpected but valid HTML</body></html>",
        )
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_skips_product_links_outside_practice_site(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="https://example.com/book">External Book</a></h3>
          <p class="price_color">£5.00</p>
        </article>
        """
        get.return_value = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            html,
        )
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_skips_malformed_product_url(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="https://[malformed/book">Broken Link</a></h3>
          <p class="price_color">£5.00</p>
        </article>
        """
        get.return_value = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            html,
        )
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_rejects_source_redirects(self, get):
        response = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            "",
        )
        response.status_code = 302
        get.return_value = response
        with self.assertRaises(requests.RequestException):
            scrape_books(limit=1)
        get.assert_called_once_with(
            "https://books.toscrape.com/catalogue/page-1.html",
            timeout=20,
            allow_redirects=False,
        )


if __name__ == "__main__":
    unittest.main()
