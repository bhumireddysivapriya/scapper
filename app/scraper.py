import logging
import math
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com/catalogue/page-1.html"
CONTEMPORARY_URL = (
    "https://books.toscrape.com/catalogue/category/books/contemporary_38/index.html"
)
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_PACING_SECONDS = 0.5
REQUEST_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.5
SOURCE_HOST = "books.toscrape.com"
USER_AGENT = "BookShelfScraper/1.0"

logger = logging.getLogger(__name__)


class SourceAccessError(requests.RequestException):
    pass


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


def _request(
    url: str,
    last_request: list[float | None],
    *,
    allow_not_found: bool = False,
) -> requests.Response:
    if not _is_allowed_source_url(url):
        raise SourceAccessError("Refusing to request a URL outside the source site")

    for attempt in range(REQUEST_RETRIES):
        if last_request[0] is not None:
            elapsed = time.monotonic() - last_request[0]
            if elapsed < REQUEST_PACING_SECONDS:
                time.sleep(REQUEST_PACING_SECONDS - elapsed)
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
                headers={"User-Agent": USER_AGENT},
            )
            last_request[0] = time.monotonic()
            if 300 <= response.status_code < 400:
                raise SourceAccessError("Unexpected redirect from source site")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < REQUEST_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
            if allow_not_found and response.status_code == 404:
                return response
            response.raise_for_status()
            if not _is_allowed_source_url(response.url):
                raise SourceAccessError(
                    "The source redirected outside its allowed host"
                )
            return response
        except SourceAccessError:
            raise
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else 0
            if status_code != 429 and status_code < 500:
                raise
            if attempt + 1 == REQUEST_RETRIES:
                logger.exception("Request failed while scraping %s", url)
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        except requests.RequestException:
            if attempt + 1 == REQUEST_RETRIES:
                logger.exception("Request failed while scraping %s", url)
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    raise requests.RequestException("Source request retries were exhausted")


def _load_robots(last_request: list[float | None]) -> RobotFileParser | None:
    robots_url = f"https://{SOURCE_HOST}/robots.txt"
    response = _request(robots_url, last_request, allow_not_found=True)
    if response.status_code == 404:
        return None
    parser = RobotFileParser(robots_url)
    parser.parse(response.text.splitlines())
    return parser


def _extract_details(html: bytes) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    category_links = soup.select("ul.breadcrumb li a")
    category = (
        category_links[-1].get_text(" ", strip=True)
        if category_links
        else None
    )
    description_heading = soup.select_one("#product_description")
    description_tag = (
        description_heading.find_next("p") if description_heading else None
    )
    description = (
        description_tag.get_text(" ", strip=True) if description_tag else None
    )
    return category, description


def scrape_books(
    limit: int = 20,
    *,
    start_url: str = BASE_URL,
) -> list[dict[str, str | float | None]]:
    if not _is_allowed_source_url(start_url):
        raise SourceAccessError("Refusing to scrape a URL outside the source site")

    books: list[dict[str, str | float | None]] = []
    seen_urls: set[str] = set()
    next_url: str | None = start_url
    visited_pages: set[str] = set()
    last_request: list[float | None] = [None]
    robots = _load_robots(last_request)

    if robots and not robots.can_fetch(USER_AGENT, start_url):
        raise SourceAccessError("robots.txt disallows scraping the catalogue")

    while next_url and len(books) < limit and next_url not in visited_pages:
        visited_pages.add(next_url)
        response = _request(next_url, last_request)
        soup = BeautifulSoup(response.content, "html.parser")

        for item in soup.select("article.product_pod"):
            title_tag = item.select_one("h3 a")
            price_tag = item.select_one(".price_color")
            availability_tag = item.select_one(".availability")
            rating_tag = item.select_one("p.star-rating")
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
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)

            image_href = image_tag.get("src") if image_tag else None
            try:
                image_url = urljoin(response.url, image_href) if image_href else None
            except ValueError:
                image_url = None
            if image_url and not _is_allowed_source_url(image_url):
                image_url = None

            rating_classes = rating_tag.get("class", []) if rating_tag else []
            rating = next(
                (value for value in rating_classes if value != "star-rating"),
                "Unknown",
            )

            category = None
            description = None
            detail_failed = False
            if not robots or robots.can_fetch(USER_AGENT, product_url):
                try:
                    detail_response = _request(product_url, last_request)
                    category, description = _extract_details(detail_response.content)
                except requests.RequestException:
                    detail_failed = True
                    logger.warning("Could not retrieve details for %s", product_url)

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
                    "category": category,
                    "description": description,
                    "detail_failed": detail_failed,
                }
            )
            if len(books) >= limit:
                break

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
        if next_url and robots and not robots.can_fetch(USER_AGENT, next_url):
            logger.warning("Stopping pagination because robots.txt disallows %s", next_url)
            next_url = None

    return books
