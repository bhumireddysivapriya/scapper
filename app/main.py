from typing import Optional

import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Book
from app.scraper import scrape_books

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Book Scraper Assignment",
    description="Scrapes public book data from a practice website and provides a REST API.",
    version="1.0.0",
)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Show the dashboard for browsing and filtering saved books."""
    return """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Book Library Dashboard</title>
        <style>
          :root {
            color-scheme: light;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: #17211b;
            background: #f5f7f4;
          }
          * { box-sizing: border-box; }
          body { margin: 0; min-width: 320px; }
          a { color: inherit; }
          .layout { min-height: 100vh; }
          .topbar {
            display: flex; align-items: center; justify-content: space-between;
            gap: 20px; padding: 18px max(24px, calc((100% - 1180px) / 2));
            background: #fff; border-bottom: 1px solid #e6ebe7;
          }
          .brand { display: flex; align-items: center; gap: 11px; font-weight: 750; }
          .brand-mark {
            display: grid; place-items: center; width: 38px; height: 38px;
            border-radius: 12px; color: #fff; background: #286343; font-size: 20px;
          }
          .nav { display: flex; gap: 22px; color: #68756c; font-size: 14px; }
          .nav a { text-decoration: none; }
          .nav a:hover { color: #286343; }
          main { width: min(1180px, calc(100% - 40px)); margin: 42px auto; }
          .heading {
            display: flex; justify-content: space-between; align-items: end;
            gap: 20px; margin-bottom: 26px;
          }
          .eyebrow {
            margin: 0 0 8px; color: #43805b; font-size: 12px;
            font-weight: 750; letter-spacing: .12em; text-transform: uppercase;
          }
          h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); letter-spacing: -.04em; }
          .subtitle { margin: 9px 0 0; color: #748078; }
          button, input {
            min-height: 42px; border-radius: 9px; font: inherit;
          }
          button {
            border: 0; padding: 0 16px; color: #fff; background: #286343;
            font-weight: 650; cursor: pointer;
          }
          button:hover { background: #204f35; }
          button:disabled { opacity: .65; cursor: wait; }
          .cards {
            display: grid; grid-template-columns: repeat(3, 1fr);
            gap: 16px; margin-bottom: 22px;
          }
          .card, .panel {
            background: #fff; border: 1px solid #e6ebe7; border-radius: 14px;
            box-shadow: 0 3px 12px rgb(25 50 35 / 3%);
          }
          .card { padding: 20px 22px; }
          .card-label { color: #748078; font-size: 13px; }
          .card-value { margin-top: 9px; font-size: 27px; font-weight: 750; }
          .panel { overflow: hidden; }
          .filters {
            display: flex; align-items: end; gap: 12px; flex-wrap: wrap;
            padding: 18px; border-bottom: 1px solid #edf0ed;
          }
          .field { display: grid; gap: 6px; }
          .field.search { flex: 1 1 240px; }
          .field.price { width: 142px; }
          label { color: #69756d; font-size: 12px; font-weight: 650; }
          input {
            width: 100%; padding: 0 12px; color: #17211b;
            background: #fff; border: 1px solid #dfe6e0; outline: none;
          }
          input:focus { border-color: #43805b; box-shadow: 0 0 0 3px #43805b20; }
          .secondary {
            color: #355542; background: #edf4ef; border: 1px solid #dce9df;
          }
          .secondary:hover { background: #e2eee5; }
          .table-head {
            display: flex; align-items: center; justify-content: space-between;
            gap: 12px; padding: 17px 20px; color: #6b776f; font-size: 13px;
          }
          .table-wrap { overflow-x: auto; }
          table { width: 100%; border-collapse: collapse; text-align: left; }
          th {
            padding: 12px 18px; color: #78837b; background: #f8faf8;
            font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
          }
          td { padding: 15px 18px; border-top: 1px solid #edf0ed; font-size: 14px; }
          td:first-child { color: #879189; font-variant-numeric: tabular-nums; }
          .book-title { min-width: 220px; max-width: 420px; font-weight: 650; }
          .price { white-space: nowrap; font-variant-numeric: tabular-nums; }
          .badge {
            display: inline-flex; padding: 5px 9px; border-radius: 999px;
            color: #286343; background: #eaf4ed; font-size: 12px; white-space: nowrap;
          }
          .badge.unavailable { color: #875a27; background: #fff3df; }
          .rating { color: #a76c16; font-weight: 700; }
          .product-link { color: #286343; font-weight: 650; text-decoration: none; }
          .product-link:hover { text-decoration: underline; }
          .message { padding: 28px 18px; color: #748078; text-align: center; }
          .error { margin: 0 18px 16px; color: #a12c2c; font-size: 14px; }
          .footer {
            display: flex; justify-content: space-between; gap: 12px; padding: 16px 20px;
            color: #879189; border-top: 1px solid #edf0ed; font-size: 12px;
          }
          @media (max-width: 650px) {
            .topbar { padding: 14px 20px; }
            .nav { gap: 13px; }
            main { margin: 28px auto; }
            .heading { align-items: start; flex-direction: column; }
            .cards { gap: 9px; }
            .card { padding: 15px 12px; }
            .card-value { font-size: 22px; }
            .field.price { flex: 1 1 120px; }
            .footer { flex-direction: column; }
          }
        </style>
      </head>
      <body>
        <div class="layout">
          <header class="topbar">
            <div class="brand"><span class="brand-mark" aria-hidden="true">B</span> BookShelf</div>
            <nav class="nav" aria-label="Main navigation">
              <a href="/">Dashboard</a><a href="/docs">API Docs</a><a href="/books">JSON API</a>
            </nav>
          </header>
          <main>
            <section class="heading">
              <div>
                <p class="eyebrow">Books to Scrape · Library</p>
                <h1>Book dashboard</h1>
                <p class="subtitle">Browse, search, and filter your collected book data.</p>
              </div>
              <button id="scrape-button" type="button">↻ &nbsp; Scrape latest books</button>
            </section>
            <section class="cards" aria-label="Book statistics">
              <article class="card"><div class="card-label">Matching books</div><div class="card-value" id="book-count">—</div></article>
              <article class="card"><div class="card-label">Average price</div><div class="card-value" id="average-price">—</div></article>
              <article class="card"><div class="card-label">In stock</div><div class="card-value" id="stock-count">—</div></article>
            </section>
            <section class="panel" aria-label="Book collection">
              <form class="filters" id="filter-form">
                <div class="field search">
                  <label for="search">Search title</label>
                  <input id="search" name="search" type="search" placeholder="Try “light” or “history”">
                </div>
                <div class="field price">
                  <label for="min-price">Minimum price (£)</label>
                  <input id="min-price" name="min_price" type="number" min="0" step="0.01" placeholder="Any">
                </div>
                <div class="field price">
                  <label for="max-price">Maximum price (£)</label>
                  <input id="max-price" name="max_price" type="number" min="0" step="0.01" placeholder="Any">
                </div>
                <button type="submit">Apply filters</button>
                <button class="secondary" id="clear-button" type="button">Clear</button>
              </form>
              <p class="error" id="error-message" role="alert" hidden></p>
              <div class="table-head">
                <strong>Scraped books</strong><span id="result-label">Loading books…</span>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr><th>ID</th><th>Title</th><th>Price</th><th>Availability</th><th>Rating</th><th>Product</th></tr>
                  </thead>
                  <tbody id="book-rows"></tbody>
                </table>
                <div class="message" id="empty-message" hidden></div>
              </div>
              <div class="footer">
                <span>Source: books.toscrape.com</span>
                <span>Prices shown in GBP · Click “Scrape latest books” to update collection</span>
              </div>
            </section>
          </main>
        </div>
        <script>
          const form = document.getElementById("filter-form");
          const rows = document.getElementById("book-rows");
          const errorMessage = document.getElementById("error-message");
          const emptyMessage = document.getElementById("empty-message");
          const scrapeButton = document.getElementById("scrape-button");

          function addCell(row, value, className) {
            const cell = document.createElement("td");
            if (className) cell.className = className;
            cell.textContent = value;
            row.appendChild(cell);
            return cell;
          }

          function renderBooks(books) {
            rows.replaceChildren();
            let totalPrice = 0;
            let inStock = 0;

            for (const book of books) {
              const row = document.createElement("tr");
              addCell(row, String(book.id));
              addCell(row, book.title || "Untitled", "book-title");
              addCell(row, `£${Number(book.price).toFixed(2)}`, "price");

              const availability = addCell(row, "");
              const badge = document.createElement("span");
              badge.className = "badge";
              badge.textContent = book.availability || "Unknown";
              if (!/in stock/i.test(badge.textContent)) {
                badge.classList.add("unavailable");
              } else {
                inStock += 1;
              }
              availability.appendChild(badge);

              addCell(row, book.rating || "Unknown", "rating");
              const productCell = addCell(row, "");
              const productLink = document.createElement("a");
              productLink.className = "product-link";
              productLink.href = book.url;
              productLink.target = "_blank";
              productLink.rel = "noopener noreferrer";
              productLink.textContent = "View book ↗";
              productCell.appendChild(productLink);

              totalPrice += Number(book.price) || 0;
              rows.appendChild(row);
            }

            document.getElementById("book-count").textContent = String(books.length);
            document.getElementById("average-price").textContent = books.length
              ? `£${(totalPrice / books.length).toFixed(2)}`
              : "£0.00";
            document.getElementById("stock-count").textContent = String(inStock);
            document.getElementById("result-label").textContent =
              `${books.length} ${books.length === 1 ? "book" : "books"}`;
            emptyMessage.hidden = books.length !== 0;
            emptyMessage.textContent = books.length
              ? ""
              : "No books found. Try changing your filters or scrape the latest books.";
          }

          async function loadBooks() {
            errorMessage.hidden = true;
            const params = new URLSearchParams(new FormData(form));
            for (const [key, value] of [...params.entries()]) {
              if (!value.trim()) params.delete(key);
            }
            document.getElementById("result-label").textContent = "Loading books…";
            try {
              const response = await fetch(`/books?${params.toString()}`);
              if (!response.ok) throw new Error("Could not load books from the API.");
              renderBooks(await response.json());
            } catch (error) {
              errorMessage.textContent = error.message;
              errorMessage.hidden = false;
              document.getElementById("result-label").textContent = "Unable to load books";
            }
          }

          form.addEventListener("submit", (event) => {
            event.preventDefault();
            loadBooks();
          });
          document.getElementById("clear-button").addEventListener("click", () => {
            form.reset();
            loadBooks();
          });
          scrapeButton.addEventListener("click", async () => {
            scrapeButton.disabled = true;
            scrapeButton.textContent = "Scraping…";
            errorMessage.hidden = true;
            try {
              const response = await fetch("/scrape?limit=20", { method: "POST" });
              const result = await response.json();
              if (!response.ok) throw new Error(result.detail || "Scraping failed.");
              await loadBooks();
            } catch (error) {
              errorMessage.textContent = error.message;
              errorMessage.hidden = false;
            } finally {
              scrapeButton.disabled = false;
              scrapeButton.textContent = "↻  Scrape latest books";
            }
          });
          loadBooks();
        </script>
      </body>
    </html>
    """


@app.post("/scrape")
def run_scraper(
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    """Scrape up to `limit` books and save only product URLs not already stored."""
    try:
        books = scrape_books(limit=limit)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve books from the source website",
        ) from exc

    urls = [item["url"] for item in books]
    existing_urls = (
        set(db.scalars(select(Book.url).where(Book.url.in_(urls))).all())
        if urls
        else set()
    )
    new_books = [
        Book(
            title=str(item["title"]),
            price=float(item["price"]),
            availability=str(item["availability"]),
            rating=str(item["rating"]),
            url=str(item["url"]),
        )
        for item in books
        if item["url"] not in existing_urls
    ]

    db.add_all(new_books)
    db.commit()
    return {
        "message": f"Scraped {len(books)} books",
        "new_books_saved": len(new_books),
    }


@app.get("/books")
def get_books(
    search: Optional[str] = Query(default=None, max_length=100),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, int | str | float]]:
    """Return saved books, optionally matching a title and inclusive price bounds."""
    query = db.query(Book)

    if search and search.strip():
        query = query.filter(Book.title.ilike(f"%{search.strip()}%"))
    if min_price is not None:
        query = query.filter(Book.price >= min_price)
    if max_price is not None:
        query = query.filter(Book.price <= max_price)

    books = query.order_by(Book.id).all()
    return [
        {
            "id": book.id,
            "title": book.title,
            "price": book.price,
            "availability": book.availability,
            "rating": book.rating,
            "url": book.url,
        }
        for book in books
    ]
