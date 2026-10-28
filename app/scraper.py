import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com/catalogue/page-1.html"
REQUEST_TIMEOUT_SECONDS = 20

logger = logging.getLogger(__name__)


def scrape_books(limit: int = 20) -> list[dict[str, str | float]]:
    books: list[dict[str, str | float]] = []
    seen_urls: set[str] = set()
    next_url: str | None = BASE_URL
    visited_pages: set[str] = set()

    while next_url and len(books) < limit and next_url not in visited_pages:
        visited_pages.add(next_url)
        try:
            response = requests.get(next_url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Request failed while scraping %s", next_url)
            raise

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

            product_url = urljoin(response.url, href)
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
                }
            )
            if len(books) >= limit:
                break

        # li.next a links to the next catalogue page, if one is available.
        next_tag = soup.select_one("li.next a")
        next_url = (
            urljoin(response.url, next_tag.get("href", ""))
            if next_tag and next_tag.get("href")
            else None
        )

    return books
