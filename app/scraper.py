import logging
import math
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com/catalogue/page-1.html"
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_PACING_SECONDS = 0.5
SOURCE_HOST = "books.toscrape.com"

logger = logging.getLogger(__name__)


def _is_allowed_source_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and hostname == SOURCE_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def scrape_books(limit: int = 20) -> list[dict[str, str | float | None]]:
    books: list[dict[str, str | float]] = []
    seen_urls: set[str] = set()
    next_url: str | None = BASE_URL
    visited_pages: set[str] = set()

    while next_url and len(books) < limit and next_url not in visited_pages:
        visited_pages.add(next_url)
        try:
            response = requests.get(
                next_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise requests.RequestException("Unexpected redirect from source site")
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Request failed while scraping %s", next_url)
            raise

        if not _is_allowed_source_url(response.url):
            raise requests.RequestException("The source redirected outside its allowed host")

        soup = BeautifulSoup(response.content, "html.parser")

        # Each article.product_pod element represents one book card.
        for item in soup.select("article.product_pod"):
            # h3 a contains the title and relative product URL.
            title_tag = item.select_one("h3 a")
            # .price_color contains the displayed GBP price.
            price_tag = item.select_one(".price_color")
            # .availability contains the stock status.
            availability_tag = item.select_one(".availability")
            # p.star-rating stores the rating in a CSS class (for example, Three).
            rating_tag = item.select_one("p.star-rating")
            # .image_container img contains the relative book-cover image URL.
            image_tag = item.select_one(".image_container img")

            title = (
                title_tag.get("title") or title_tag.get_text(strip=True)
                if title_tag
                else ""
            )
            href = title_tag.get("href") if title_tag else None
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price_text = price_text.replace("Â£", "").replace("£", "").strip()

            if not title or not href or not price_text:
                logger.warning("Skipping a book card with missing title, URL, or price")
                continue

            try:
                price = float(price_text)
            except ValueError:
                logger.warning("Skipping book %r with an invalid price", title)
                continue
            if not math.isfinite(price) or price < 0:
                logger.warning("Skipping book %r with an invalid price", title)
                continue

            try:
                product_url = urljoin(response.url, href)
            except ValueError:
                logger.warning("Skipping a book card with a malformed product URL")
                continue
            if not _is_allowed_source_url(product_url):
                logger.warning("Skipping a book card with an unexpected product URL")
                continue
            image_href = image_tag.get("src") if image_tag else None
            try:
                image_url = urljoin(response.url, image_href) if image_href else None
            except ValueError:
                image_url = None
            if image_url and not _is_allowed_source_url(image_url):
                image_url = None
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)

            rating_classes = rating_tag.get("class", []) if rating_tag else []
            rating = next(
                (value for value in rating_classes if value != "star-rating"),
                "Unknown",
            )

            books.append(
                {
                    "title": title,
                    "price": price,
                    "availability": (
                        availability_tag.get_text(" ", strip=True)
                        if availability_tag
                        else "Unknown"
                    ),
                    "rating": rating,
                    "url": product_url,
                    "image_url": image_url,
                }
            )
            if len(books) >= limit:
                break

        # li.next a links to the next catalogue page, if one is available.
        next_tag = soup.select_one("li.next a")
        try:
            next_url = (
                urljoin(response.url, next_tag.get("href", ""))
                if next_tag and next_tag.get("href")
                else None
            )
        except ValueError:
            logger.warning("Stopping pagination at a malformed next-page URL")
            next_url = None
        if next_url and not _is_allowed_source_url(next_url):
            logger.warning("Stopping pagination at an unexpected next-page URL")
            next_url = None
        if next_url and len(books) < limit:
            time.sleep(REQUEST_PACING_SECONDS)

    return books
