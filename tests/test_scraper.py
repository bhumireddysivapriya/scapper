import unittest
from unittest.mock import patch

import requests

from app.scraper import scrape_books


def make_response(url: str, html: str):
    class Response:
        content = html.encode("utf-8")
        text = html
        status_code = 200

        def __init__(self) -> None:
            self.url = url

        @staticmethod
        def raise_for_status() -> None:
            return None

    return Response()


def robots_response():
    return make_response(
        "https://books.toscrape.com/robots.txt",
        "User-agent: *\nAllow: /\n",
    )


class ScrapeBooksTests(unittest.TestCase):
    @patch("app.scraper.time.sleep")
    @patch("app.scraper.requests.get")
    def test_scrapes_all_pages_from_category_start_url(self, get, sleep):
        category_url = (
            "https://books.toscrape.com/catalogue/category/books/"
            "contemporary_38/index.html"
        )
        first_page = """
        <article class="product_pod">
          <h3><a href="../../../book-one_1/index.html" title="Book One">Book One</a></h3>
          <p class="price_color">£12.50</p><p class="availability">In stock</p>
          <p class="star-rating Five"></p>
        </article>
        <li class="next"><a href="page-2.html">next</a></li>
        """
        second_page = """
        <article class="product_pod">
          <h3><a href="../../../book-two_2/index.html" title="Book Two">Book Two</a></h3>
          <p class="price_color">£8.99</p><p class="availability">In stock</p>
          <p class="star-rating Four"></p>
        </article>
        """
        detail_page = """
        <ul class="breadcrumb"><li><a>Home</a></li><li><a>Books</a></li>
        <li><a>Contemporary</a></li></ul>
        """
        get.side_effect = [
            robots_response(),
            make_response(category_url, first_page),
            make_response(
                "https://books.toscrape.com/catalogue/book-one_1/index.html",
                detail_page,
            ),
            make_response(
                "https://books.toscrape.com/catalogue/category/books/"
                "contemporary_38/page-2.html",
                second_page,
            ),
            make_response(
                "https://books.toscrape.com/catalogue/book-two_2/index.html",
                detail_page,
            ),
        ]

        books = scrape_books(limit=1000, start_url=category_url)

        self.assertEqual([book["title"] for book in books], ["Book One", "Book Two"])
        self.assertEqual([book["category"] for book in books], ["Contemporary"] * 2)
        self.assertEqual(get.call_args_list[1].args[0], category_url)
        self.assertEqual(
            get.call_args_list[3].args[0],
            "https://books.toscrape.com/catalogue/category/books/"
            "contemporary_38/page-2.html",
        )
        self.assertEqual(sleep.call_count, 4)

    def test_rejects_category_start_url_outside_source(self):
        with self.assertRaises(requests.RequestException):
            scrape_books(start_url="https://example.com/category")

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
        first_detail = """
        <ul class="breadcrumb"><li><a>Home</a></li><li><a>Books</a></li>
        <li><a>Travel</a></li></ul>
        <div id="product_description"></div><p>A travel book.</p>
        """
        second_detail = """
        <ul class="breadcrumb"><li><a>Home</a></li><li><a>Books</a></li>
        <li><a>History</a></li></ul>
        <div id="product_description"></div><p>A history book.</p>
        """
        get.side_effect = [
            robots_response(),
            make_response(
                "https://books.toscrape.com/catalogue/page-1.html",
                first_page,
            ),
            make_response(
                "https://books.toscrape.com/catalogue/book-one_1/index.html",
                first_detail,
            ),
            make_response(
                "https://books.toscrape.com/catalogue/page-2.html",
                second_page,
            ),
            make_response(
                "https://books.toscrape.com/catalogue/book-two_2/index.html",
                second_detail,
            ),
        ]

        books = scrape_books(limit=2)

        self.assertEqual(len(books), 2)
        self.assertEqual(books[0]["title"], "Book One")
        self.assertEqual(books[0]["price"], 12.5)
        self.assertEqual(books[0]["rating"], "Three")
        self.assertEqual(books[0]["category"], "Travel")
        self.assertEqual(books[0]["description"], "A travel book.")
        self.assertEqual(
            books[0]["url"],
            "https://books.toscrape.com/catalogue/book-one_1/index.html",
        )
        self.assertEqual(
            books[0]["image_url"],
            "https://books.toscrape.com/media/cache/cover-one.jpg",
        )
        self.assertEqual(books[1]["title"], "Book Two")
        self.assertEqual(books[1]["category"], "History")
        self.assertEqual(get.call_count, 5)
        self.assertEqual(sleep.call_count, 4)

    @patch("app.scraper.requests.get")
    def test_skips_card_with_invalid_price(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="book_1/index.html" title="Book">Book</a></h3>
          <p class="price_color">not a price</p>
        </article>
        """
        get.side_effect = [
            robots_response(),
            make_response("https://books.toscrape.com/catalogue/page-1.html", html),
        ]

        self.assertEqual(scrape_books(), [])

    @patch("app.scraper.requests.get")
    def test_skips_non_finite_price(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="book_1/index.html" title="Book">Book</a></h3>
          <p class="price_color">£NaN</p>
        </article>
        """
        get.side_effect = [
            robots_response(),
            make_response("https://books.toscrape.com/catalogue/page-1.html", html),
        ]
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_handles_missing_optional_elements(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="book_1/index.html">Book</a></h3>
          <p class="price_color">£51.77</p>
        </article>
        """
        get.side_effect = [
            robots_response(),
            make_response("https://books.toscrape.com/catalogue/page-1.html", html),
            make_response(
                "https://books.toscrape.com/catalogue/book_1/index.html",
                "<html><body>No optional details.</body></html>",
            ),
        ]

        books = scrape_books(limit=1)

        self.assertEqual(books[0]["title"], "Book")
        self.assertEqual(books[0]["price"], 51.77)
        self.assertEqual(books[0]["availability"], "Unknown")
        self.assertEqual(books[0]["rating"], "Unknown")
        self.assertIsNone(books[0]["image_url"])

    @patch("app.scraper.time.sleep")
    @patch("app.scraper.requests.get", side_effect=requests.Timeout("timed out"))
    def test_propagates_request_errors_for_api_handling(self, get, sleep):
        with self.assertRaises(requests.Timeout):
            scrape_books(limit=1)
        self.assertEqual(get.call_count, 3)

    @patch("app.scraper.requests.get")
    def test_malformed_html_returns_empty_results(self, get):
        get.side_effect = [
            robots_response(),
            make_response(
                "https://books.toscrape.com/catalogue/page-1.html",
                "<html><body>Unexpected but valid HTML</body></html>",
            ),
        ]
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_skips_product_links_outside_practice_site(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="https://example.com/book">External Book</a></h3>
          <p class="price_color">£5.00</p>
        </article>
        """
        get.side_effect = [
            robots_response(),
            make_response("https://books.toscrape.com/catalogue/page-1.html", html),
        ]
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_skips_malformed_product_url(self, get):
        html = """
        <article class="product_pod">
          <h3><a href="https://[malformed/book">Broken Link</a></h3>
          <p class="price_color">£5.00</p>
        </article>
        """
        get.side_effect = [
            robots_response(),
            make_response("https://books.toscrape.com/catalogue/page-1.html", html),
        ]
        self.assertEqual(scrape_books(limit=1), [])

    @patch("app.scraper.requests.get")
    def test_rejects_source_redirects(self, get):
        response = make_response(
            "https://books.toscrape.com/catalogue/page-1.html",
            "",
        )
        response.status_code = 302
        get.side_effect = [robots_response(), response]
        with self.assertRaises(requests.RequestException):
            scrape_books(limit=1)
        self.assertEqual(
            get.call_args_list[1].args[0],
            "https://books.toscrape.com/catalogue/page-1.html",
        )
        self.assertEqual(
            get.call_args_list[1].kwargs,
            {
                "timeout": 20,
                "allow_redirects": False,
                "headers": {"User-Agent": "BookShelfScraper/1.0"},
            },
        )


if __name__ == "__main__":
    unittest.main()
