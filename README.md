# Book Scraper Assignment

A beginner-friendly web scraper and REST API that collects public book data from [Books to Scrape](https://books.toscrape.com/), a website made for scraping practice. It stores results in SQLite and lets users browse, search, and filter the collected books.

## Features

- Scrapes book titles, prices, availability, ratings, and product links.
- Follows the practice site's pagination until it reaches the requested limit (up to 50 books).
- Saves books in SQLite and avoids duplicates using each product URL.
- Migrates existing rows from the legacy `books` table into the `products` table on startup without deleting the old table.
- Provides a FastAPI homepage and interactive API documentation.
- Includes a responsive Bookshelf-style dashboard with sidebar navigation, book-cover thumbnails, and paginated product table.
- Lets users download all saved or currently filtered products as a CSV file.
- Shows collection-wide book statistics, rating stars, prices, and in-stock/out-of-stock/unknown counts.
- Provides paginated product search, price and availability filters, individual product lookup, and a database health check.
- Shows collection-wide dashboard statistics for total books, the top rating, average/minimum/maximum price, in-stock, out-of-stock, and unknown availability.
- Limits scrape batches and applies a process-local cooldown to reduce repeated public scrape requests.

## Project structure

```text
book-scraper-assignment/
├── app/
│   ├── __init__.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   └── scraper.py
├── tests/
│   ├── test_api.py
│   ├── test_database.py
│   └── test_scraper.py
├── docs/
│   ├── Book_Scraper_Project_Report.md
│   └── screenshots/
│       ├── api-docs.png
│       └── dashboard.png
├── render.yaml
├── .gitignore
├── README.md
└── requirements.txt
```

## Run locally

Requires Python 3.10 or newer.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Run the automated test suite from the project directory:

```powershell
python -m pytest -q
```

### macOS/Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the homepage or [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for Swagger UI. The SQLite database (`books.db`) is created automatically in the current working directory.

## How the project works

The application has four main steps:

1. **Scrape:** `app/scraper.py` requests the catalogue pages from Books to Scrape. BeautifulSoup finds each book card and extracts its title, GBP price, availability, rating, and product URL. A missing title, price, or URL makes that card invalid and it is skipped; missing availability or rating is shown as `Unknown`.
2. **Store:** `app/models.py` describes the `products` table. SQLAlchemy in `app/database.py` creates and connects to the local `books.db` SQLite file. The product URL is unique so the same book cannot be stored twice. Existing rows from the older `books` table are copied during startup, while the original table is kept.
3. **Serve the API:** `app/main.py` provides routes for the dashboard, scraping, and reading/searching saved books. The API returns JSON for book records and scraping results.
4. **Display:** the homepage uses browser JavaScript to request `/products` in ten-record pages, then renders the returned records in the dashboard. Filtering and global search ask the API for matching records; scraping calls `/scrape` and reloads the table when it finishes.

### Dashboard guide

- **Total books** is the number of records in the saved collection. Dashboard summary cards are collection-wide and do not change when table filters are applied.
- **Top-rated book** shows the highest rating found and up to five book titles with that rating; the subtitle reports how many books share it.
- **Average price**, **Lowest price**, and **Highest price** summarize prices across the full collection in GBP.
- **In stock** and **Out of stock** count books whose availability text explicitly reports those states. **Availability unknown** counts missing or unrecognized states so they are not silently included in either total.
- The table result count and rows reflect the currently applied title, price, and availability filters. Pagination controls navigate ten products at a time.
- **Search title** finds titles containing the text entered, without case sensitivity.
- **Minimum price** and **Maximum price** filter by an inclusive price range. Either field can be left blank.
- **Apply filters** reloads the table with the selected search, price, and availability values. **Clear all** removes all filters. The global search bar searches titles as you type.
- **Download CSV** exports all matching books, not only the ten currently visible in the table. The file includes title, price, availability, rating, product URL, and cover image URL.
- **Scrape latest books** requests up to 20 books from the practice website. Existing product URLs are not inserted again; missing cover URLs can be refreshed, and the dashboard reloads after scraping.
- The table shows each saved book's row number, cover thumbnail (or placeholder), title, price, availability, star rating, and a link to its page on the practice site. On narrow screens, the table can be scrolled horizontally.

### Swagger UI (`/docs`) guide

Swagger UI is an interactive page generated by FastAPI from the API routes. Expand an operation to see its purpose and parameters. Select **Try it out**, fill in any values, and choose **Execute** to send the request and view its status and response.

| Route | What it does | Parameters |
|---|---|---|
| `GET /` | Returns the dashboard HTML page. | None |
| `GET /health` | Checks API and SQLite connectivity. | None |
| `GET /dashboard/stats` | Returns total books, top-rated titles, price summary, and availability counts for the full collection. | None |
| `POST /scrape` | Fetches books from the fixed source site and saves new records. | `limit`: defaults to `20`, minimum `1`, maximum `50`; the operation has a process-local 30-second cooldown. |
| `GET /products` | Returns a paginated product object. | `search`, `min_price`, `max_price`, `availability`, `limit` (1–100), and `offset`. |
| `GET /products/export.csv` | Downloads matching products as `books.csv`; does not limit export to the current table page. | `search`, `min_price`, `max_price`, and `availability`. |
| `GET /products/{product_id}` | Returns one saved product. | Product ID in the path; missing IDs return `404`. |
| `GET /books` | Backward-compatible saved-book JSON array. | `search`, `min_price`, `max_price`, and `availability`; no pagination. |

For example, `GET /products?search=light&min_price=10&max_price=60&availability=In%20stock` returns matching products within the inclusive price range. An invalid parameter (for example, `limit=0`) returns HTTP `422` with validation details. If the source site cannot be reached while scraping, the API returns HTTP `502`.

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Book dashboard with statistics, filters, and a table of saved books |
| `GET` | `/health` | Checks API and database connectivity |
| `GET` | `/dashboard/stats` | Returns collection-wide total, rating, price, and stock summaries |
| `POST` | `/scrape?limit=20` | Collects up to 20 books; `limit` can be 1–50 and repeated calls are rate-limited |
| `GET` | `/products?limit=20&offset=0` | Lists products with pagination and a total count |
| `GET` | `/products?search=light&min_price=10&max_price=50&availability=In%20stock` | Combines title, inclusive price, and availability filters |
| `GET` | `/products/export.csv?search=light` | Downloads all matching books as a CSV attachment |
| `GET` | `/products/{product_id}` | Returns one product by database ID, or `404` |
| `GET` | `/books` | Backward-compatible, unpaginated books list |
| `GET` | `/books?search=light&min_price=10&max_price=50` | Backward-compatible title and price filters |

`/products` returns an object with `total`, `limit`, `offset`, and a `products` array. The legacy `/books` endpoint keeps returning a JSON array, so existing clients and the dashboard continue to work. A scraping response reports `products_collected`, `products_inserted`, and `products_skipped`; duplicate URLs count as skipped. Invalid filter ranges return HTTP `422`, a missing product returns `404`, a source-site network failure returns `502`, and a concurrent or too-frequent scrape returns `429`.

### Test each endpoint locally

In Swagger UI, expand each route and select **Try it out**. Or use a terminal:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/dashboard/stats
curl -X POST "http://127.0.0.1:8000/scrape?limit=20"
curl "http://127.0.0.1:8000/products?limit=10&offset=0"
curl "http://127.0.0.1:8000/products?search=light&min_price=10&max_price=50&availability=In%20stock"
curl -OJ "http://127.0.0.1:8000/products/export.csv?search=light"
curl http://127.0.0.1:8000/products/1
curl http://127.0.0.1:8000/books
curl "http://127.0.0.1:8000/books?search=light"
curl "http://127.0.0.1:8000/books?min_price=10&max_price=50"
```

The scrape route returns counts of collected, inserted, and skipped records. Repeating a scrape cannot add duplicate URLs. If the source website cannot be reached, the route responds with HTTP 502. Scraping only targets `books.toscrape.com`, observes a short delay between catalogue pages, and is throttled per application process.

## Push to GitHub

This project is already connected to `https://github.com/bhumireddysivapriya/scapper.git`. Review and push changes from the project folder:

```bash
git add .
git commit -m "Improve book scraper API and report"
git push origin main
```

If using a different GitHub repository, create it first and set its URL as the `origin` remote. Do not initialize a new Git repository over this existing history.

## Deploy on Render

1. Push the project to GitHub.
2. In Render, choose **New → Blueprint** to use `render.yaml`, or create a Web Service manually with these settings:

| Setting | Value |
|---|---|
| Runtime | Python 3.10 |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Instance type | Free |

3. Deploy, then open `https://<your-service-name>.onrender.com/` for the dashboard or `/docs` for the API.

If the shell reports `gunicorn: command not found`, replace any `gunicorn` Start Command in the Render service settings with `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Uvicorn is installed by `requirements.txt`; this project does not use Gunicorn.

**Storage note:** `DATABASE_URL` can select a SQLite database location; by default the app uses `sqlite:///./books.db`. For example, with a persistent disk mounted at `/var/data`, set `DATABASE_URL=sqlite:////var/data/books.db`. Render's free filesystem is ephemeral, so SQLite data can be lost on restart or redeploy. Configure supported persistent storage and point `DATABASE_URL` at that disk if persistence is required. Deployment has not been performed or verified as part of this project update.

## Limitations and future improvements

- Data is refreshed only when someone calls `POST /scrape`.
- The free deployment's SQLite file is not durable across service restarts.
- The process-local scrape cooldown is not shared across multiple server instances.
- Free Render local storage is not durable across service restarts.
- Possible improvements include scheduled scraping, richer pagination controls, and a managed persistent database.
