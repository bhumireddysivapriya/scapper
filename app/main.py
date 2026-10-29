import csv
from io import StringIO
import logging
import threading
import time
from typing import Any

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Select, case, func, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from app.database import get_db, initialize_database
from app.jobs import create_scrape_job, run_scrape_job
from app.models import PriceHistory, Product, ScrapeJob
from app.schemas import (
    DashboardStats,
    PriceHistoryResponse,
    ProductPage,
    ProductResponse,
    ScrapeJobResponse,
)
from app.scraper import CONTEMPORARY_URL, scrape_books

logger = logging.getLogger(__name__)
try:
    initialize_database()
except SQLAlchemyError:
    logger.exception("Application database initialization failed")
    raise

SCRAPE_COOLDOWN_SECONDS = 30
_scrape_lock = threading.Lock()
_last_scrape_at: float | None = None

app = FastAPI(
    title="Book Scraper Assignment",
    description="Scrapes public book data from a practice website and provides a REST API.",
    version="1.0.0",
)


def _product_upsert_statement(
    dialect_name: str,
    records: list[dict[str, Any]],
) -> Insert:
    if dialect_name == "sqlite":
        statement = sqlite_insert(Product).values(records)
    elif dialect_name == "postgresql":
        statement = postgresql_insert(Product).values(records)
    else:
        raise RuntimeError(f"Product persistence is unsupported for {dialect_name}")
    return statement.on_conflict_do_update(
        index_elements=[Product.url],
        set_={"image_url": statement.excluded.image_url},
        where=statement.excluded.image_url.is_not(None),
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
        <title>Book Analytics | BookShelf</title>
        <style>
          :root {
            color-scheme: light;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: #132136;
            background: #f4f8f6;
          }
          * { box-sizing: border-box; }
          body { margin: 0; min-width: 320px; }
          a { color: inherit; }
          .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
          .layout { min-height: 100vh; }
          .workspace { min-height: 100vh; }
          .topbar {
            position: sticky; top: 0; z-index: 2; display: flex;
            align-items: center; justify-content: space-between; gap: 20px;
            min-height: 76px; padding: 12px 24px;
            background: #f7faf8; border-bottom: 1px solid #e6eee9;
          }
          .page-heading { display: grid; gap: 3px; }
          .page-heading p { margin: 0; color: #728078; font-size: 12px; }
          .global-search {
            display: flex; align-items: center; gap: 9px; width: min(440px, 55%);
            min-height: 40px; padding: 0 12px; color: #7a867d;
            border: 1px solid #e1e7e2; border-radius: 9px; background: #fbfcfb;
          }
          .global-search input {
            width: 100%; min-height: 36px; padding: 0; border: 0;
            background: transparent; outline: 0; font-size: 12px;
          }
          .top-actions { display: flex; align-items: center; gap: 18px; }
          .last-updated { display: flex; align-items: center; gap: 9px; color: #62736a; font-size: 11px; }
          .last-updated strong { display: block; margin-top: 3px; color: #27382f; font-size: 11px; font-weight: 550; }
          .refresh-button { min-height: 36px; border-radius: 9px; background: #1d7b4a; font-size: 11px; }
          .scrape-button { min-height: 36px; border-radius: 9px; font-size: 11px; }
          .scrape-status { margin: 0 0 12px; color: #355542; font-size: 12px; }
          .top-link { color: #66746b; font-size: 12px; text-decoration: none; }
          .profile {
            display: flex; align-items: center; gap: 8px; color: #506056;
            font-size: 12px; font-weight: 650; text-decoration: none;
          }
          .avatar {
            display: grid; place-items: center; width: 30px; height: 30px;
            border-radius: 50%; color: #fff; background: #286343; font-weight: 750;
          }
          main { width: 100%; max-width: 1500px; margin: 0 auto; padding: 14px 16px 28px; }
          .dashboard-title {
            margin: 0; font-size: clamp(23px, 2.5vw, 29px);
            letter-spacing: -.03em;
          }
          button, input {
            min-height: 42px; border-radius: 9px; font: inherit;
          }
          select {
            min-height: 42px; border: 1px solid #dfe6e0; border-radius: 9px;
            padding: 0 12px; color: #17211b; background: #fff; font: inherit;
          }
          button {
            border: 0; padding: 0 16px; color: #fff; background: #286343;
            font-weight: 650; cursor: pointer;
          }
          button:hover { background: #204f35; }
          button:disabled { opacity: .65; cursor: wait; }
          .cards {
            display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 9px; margin: 0 0 11px;
          }
          .card, .panel {
            background: #fff; border: 1px solid #e8efeb; border-radius: 13px;
            box-shadow: 0 3px 12px rgb(25 50 35 / 3%);
          }
          .card {
            position: relative; min-height: 94px; padding: 15px 12px 11px 55px;
            overflow: hidden;
          }
          .card-icon {
            position: absolute; top: 14px; left: 13px; display: grid;
            place-items: center; width: 34px; height: 34px; border-radius: 10px;
            color: #1d7b4a; background: #e1f4e8; font-size: 18px;
          }
          .card:nth-child(2) { background: linear-gradient(120deg, #fffdf6, #fff9e9); }
          .card:nth-child(2) .card-icon { color: #d18400; background: #fff0c8; }
          .card:nth-child(3) { background: linear-gradient(120deg, #f8fbff, #f0f6ff); }
          .card:nth-child(3) .card-icon { color: #286bc4; background: #e1edff; }
          .card:nth-child(4) { background: linear-gradient(120deg, #fffafa, #fff2f2); }
          .card:nth-child(4) .card-icon { color: #d44b4b; background: #ffe3e3; }
          .card:nth-child(5) { background: linear-gradient(120deg, #fdfaff, #f7f1ff); }
          .card:nth-child(5) .card-icon { color: #8c4ed1; background: #eee0ff; }
          .card-label { color: #748078; font-size: 11px; }
          .card-value { margin-top: 7px; font-size: 21px; font-weight: 750; }
          .card-detail {
            margin-top: 4px; color: #748078; font-size: 10px;
            line-height: 1.45; overflow-wrap: anywhere;
          }
          .top-rated-value { font-size: 15px; line-height: 1.25; }
          .top-stars { color: #e79912; letter-spacing: 1px; }
          .analytics-grid {
            display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 12px; margin-bottom: 12px;
          }
          .chart-panel { position: relative; min-width: 0; padding: 20px 22px; }
          .chart-panel:nth-child(-n+2) { grid-column: span 3; }
          .chart-panel:nth-child(n+3) { grid-column: span 3; }
          .distribution-panel { min-height: 390px; border-radius: 18px; }
          .chart-heading { display: flex; align-items: center; gap: 16px; min-height: 68px; margin-bottom: 16px; }
          .chart-icon { display: grid; flex: 0 0 64px; place-items: center; width: 64px; height: 64px; border-radius: 20px; color: #319c68; background: #eaf6ef; font-size: 30px; }
          .price-panel .chart-icon { color: #4a8eea; background: #edf4ff; }
          .chart-heading-copy { min-width: 0; }
          .chart-title { margin: 0; color: #123143; font-size: clamp(17px, 1.5vw, 23px); letter-spacing: -.025em; }
          .chart-subtitle { margin: 6px 0 0; color: #657887; font-size: 14px; line-height: 1.4; }
          .chart-total { flex: 0 0 auto; margin-left: auto; padding: 10px 15px; border-radius: 13px; color: #5e9c7d; background: #eef7f1; font-size: 13px; }
          .chart-total strong { display: block; margin-top: 2px; color: #194b39; font-size: 21px; line-height: 1.1; font-variant-numeric: tabular-nums; }
          .chart-plot { display: block; width: 100%; height: auto; overflow: visible; }
          .chart-gridline { stroke: #e8eef0; stroke-width: 1; }
          .chart-axis { stroke: #bac6cc; stroke-width: 1.2; }
          .chart-tick, .chart-label, .chart-axis-title { fill: #536878; font-family: inherit; }
          .chart-tick { font-size: 13px; }
          .chart-label { font-size: 13px; }
          .chart-axis-title { fill: #354d5d; font-size: 14px; }
          .chart-count { fill: #174b3b; font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
          .chart-bar { transition: opacity .2s ease; }
          .highlight-table-wrap { overflow-x: auto; }
          .highlight-table { min-width: 500px; }
          .highlight-table th { padding: 7px 8px; color: #6d7f77; background: #f3f8f5; font-size: 8px; }
          .highlight-table td { padding: 5px 8px; font-size: 10px; }
          .highlight-table td:first-child { width: 28px; }
          .highlight-book { display: flex; align-items: center; gap: 8px; min-width: 180px; max-width: 260px; }
          .highlight-cover { width: 24px; height: 36px; object-fit: cover; border-radius: 3px; background: #eef4ef; }
          .highlight-book a { overflow: hidden; color: #25372e; text-decoration: none; text-overflow: ellipsis; white-space: nowrap; }
          .highlight-book a:hover { color: #1d7b4a; }
          .chart-empty { color: #879189; font-size: 11px; }
          .chart-empty { color: #879189; font-size: 11px; }
          .chart-note { margin: 12px 0 0; color: #879189; font-size: 10px; line-height: 1.5; }
          .panel { overflow: hidden; margin-bottom: 13px; }
          .filters {
            display: grid; grid-template-columns: minmax(220px, 1fr) repeat(4, minmax(115px, auto)) auto;
            align-items: center; gap: 9px; margin-bottom: 11px;
          }
          .field { display: grid; gap: 6px; }
          .field.search { display: flex; align-items: center; gap: 8px; min-height: 38px; padding: 0 11px; color: #7a8a82; border: 1px solid #e1e9e4; border-radius: 9px; background: #fff; }
          .field.search input { min-height: 34px; padding: 0; border: 0; box-shadow: none; }
          .field.price { width: 120px; }
          label { color: #69756d; font-size: 11px; font-weight: 650; }
          input {
            width: 100%; min-height: 38px; padding: 0 11px; color: #17211b;
            background: #fff; border: 1px solid #dfe6e0; outline: none;
          }
          select { min-height: 38px; padding: 0 11px; color: #25372e; border-color: #e1e9e4; background: #fff; font-size: 11px; }
          button { min-height: 38px; border-radius: 8px; font-size: 12px; }
          input:focus { border-color: #43805b; box-shadow: 0 0 0 3px #43805b20; }
          .secondary {
            color: #355542; background: #edf4ef; border: 1px solid #dce9df;
          }
          .secondary:hover { background: #e2eee5; }
          .clear-button { min-height: 34px; color: #566a60; background: transparent; border: 1px solid #e1e9e4; }
          .table-head {
            display: flex; align-items: center; justify-content: space-between;
            gap: 12px; padding: 13px 17px; color: #34443a; font-size: 13px;
          }
          .table-actions { display: flex; align-items: center; gap: 12px; }
          .sort-control { display: flex; align-items: center; gap: 7px; color: #718078; font-size: 10px; }
          .sort-control select { min-height: 32px; }
          .download-button {
            display: inline-flex; align-items: center; justify-content: center;
            min-height: 34px; padding: 0 11px; border: 1px solid #dce9df;
            border-radius: 8px; color: #355542; background: #edf4ef;
            font-size: 11px; font-weight: 650; text-decoration: none; white-space: nowrap;
          }
          .download-button:hover { background: #e2eee5; }
          .scrape-actions { display: flex; gap: 7px; }
          .history-list { padding: 14px 17px; color: #748078; font-size: 11px; }
          .history-entry { display: grid; grid-template-columns: 1fr auto auto; gap: 16px; padding: 8px 0; border-bottom: 1px solid #edf0ed; }
          .history-entry:last-child { border-bottom: 0; }
          .history-status { color: #286343; text-transform: capitalize; }
          .table-wrap { overflow-x: auto; }
          table { width: 100%; border-collapse: collapse; text-align: left; }
          th {
            padding: 10px 12px; color: #78837b; background: #f8faf8;
            font-size: 10px; letter-spacing: .06em; text-transform: uppercase;
          }
          td { padding: 8px 12px; border-top: 1px solid #edf0ed; font-size: 12px; }
          td:first-child { color: #879189; font-variant-numeric: tabular-nums; }
          .book-title { min-width: 180px; max-width: 360px; font-weight: 650; }
          .cover {
            display: block; width: 34px; height: 48px; object-fit: cover;
            border-radius: 4px; background: #edf3ee; box-shadow: 0 2px 5px #17211b22;
          }
          .cover-placeholder {
            display: grid; place-items: center; width: 34px; height: 48px;
            border-radius: 4px; background: #eef4ef; font-size: 20px;
          }
          .price { white-space: nowrap; font-variant-numeric: tabular-nums; }
          .badge {
            display: inline-flex; padding: 5px 9px; border-radius: 999px;
            color: #286343; background: #eaf4ed; font-size: 12px; white-space: nowrap;
          }
          .badge.unavailable { color: #875a27; background: #fff3df; }
          .badge.unknown { color: #68756c; background: #eef1ef; }
          .rating { color: #a76c16; font-weight: 700; }
          .stars { color: #e79912; font-size: 14px; letter-spacing: 1px; white-space: nowrap; }
          .action-link {
            display: inline-flex; align-items: center; gap: 5px; padding: 7px 9px;
            border: 1px solid #e2e8e3; border-radius: 7px; color: #42554a;
            font-size: 11px; text-decoration: none; white-space: nowrap;
          }
          .pagination {
            display: flex; align-items: center; justify-content: space-between;
            gap: 12px; padding: 10px 15px; color: #78837b; border-top: 1px solid #edf0ed;
            font-size: 11px;
          }
          .page-controls { display: flex; gap: 5px; }
          .page-button {
            min-width: 30px; min-height: 30px; padding: 0 8px; color: #536258;
            background: #fff; border: 1px solid #e2e8e3;
          }
          .page-button.current { color: #fff; background: #286343; border-color: #286343; }
          .loading { opacity: .6; pointer-events: none; }
          [hidden] { display: none !important; }
          .product-link { color: #286343; font-weight: 650; text-decoration: none; }
          .product-link:hover { text-decoration: underline; }
          .message { padding: 28px 18px; color: #748078; text-align: center; }
          .error { margin: 0 18px 16px; color: #a12c2c; font-size: 14px; }
          .footer {
            display: flex; justify-content: space-between; gap: 12px; padding: 16px 20px;
            color: #879189; border-top: 1px solid #edf0ed; font-size: 12px;
          }
          @media (max-width: 1080px) {
            main { padding-right: 20px; padding-left: 20px; }
            .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .card { padding-left: 48px; }
            .card-icon { left: 9px; width: 31px; height: 31px; }
            .analytics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .chart-panel:nth-child(n) { grid-column: span 1; }
            .filters { grid-template-columns: repeat(4, minmax(0, 1fr)); }
            .field.search { grid-column: span 2; }
          }
          @media (max-width: 760px) {
            .topbar { position: static; min-height: 64px; padding: 10px 14px; flex-wrap: wrap; }
            .top-actions { justify-content: flex-end; width: 100%; gap: 8px; }
            .last-updated { display: none; }
            main { padding: 18px 14px 25px; }
            .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
            .analytics-grid { grid-template-columns: 1fr; gap: 8px; }
            .chart-panel:nth-child(n) { grid-column: auto; }
            .card { min-height: 90px; padding: 13px 9px 10px 46px; }
            .card-icon { top: 12px; left: 8px; width: 30px; height: 30px; }
            .card-label { font-size: 11px; }
            .card-value { font-size: 19px; }
            .top-rated-value { font-size: 13px; }
            .filters { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
            .field.search { grid-column: span 2; }
            .field.price { flex: 1 1 100px; width: auto; }
            .table-head { padding: 12px; }
            .table-actions { align-items: flex-end; flex-direction: column; }
            .scrape-actions { flex-wrap: wrap; justify-content: flex-end; }
            .sort-control { align-self: flex-end; }
            th, td { padding-right: 9px; padding-left: 9px; }
            .book-title { min-width: 145px; }
            .pagination { align-items: flex-start; flex-direction: column; }
            .page-controls { align-self: flex-end; }
          }
          @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
          }
        </style>
      </head>
      <body>
        <div class="layout">
          <div class="workspace">
          <header class="topbar">
            <div class="page-heading">
              <h1 class="dashboard-title">Book Analytics</h1>
              <p>Insights from your scraped book data</p>
            </div>
            <div class="top-actions">
              <div class="last-updated"><span aria-hidden="true">▦</span><span>Last updated<strong id="last-updated">—</strong></span></div>
              <button class="scrape-button" id="scrape-button" type="button">Scrape Books</button>
              <button class="refresh-button" id="refresh-button" type="button">↻ &nbsp; Refresh Data</button>
            </div>
          </header>
          <main id="dashboard">
            <p class="scrape-status" id="scrape-status" role="status" aria-live="polite" hidden></p>
            <section class="cards" id="analytics" aria-label="Collection statistics" aria-live="polite">
              <article class="card">
                <span class="card-icon" aria-hidden="true">▤</span>
                <div class="card-label">Total books</div>
                <div class="card-value" id="book-count">—</div>
                <div class="card-detail">In the saved collection</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">★</span>
                <div class="card-label">Average Rating</div>
                <div class="card-value" id="average-rating">—</div>
                <div class="card-detail" id="average-rating-change">Across rated books</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">◇</span>
                <div class="card-label">Average price</div>
                <div class="card-value" id="average-price">—</div>
                <div class="card-detail">Across all saved books</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">▥</span>
                <div class="card-label">Highest Price</div>
                <div class="card-value" id="max-price-stat">—</div>
                <div class="card-detail" id="highest-price-title">Across all books</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">↓</span>
                <div class="card-label">Lowest price</div>
                <div class="card-value" id="min-price-stat">—</div>
                <div class="card-detail" id="lowest-price-title">Across all books</div>
              </article>
            </section>
            <p class="error dashboard-error" id="error-message" role="alert" hidden></p>
            <section class="analytics-grid" id="visual-analytics" aria-label="Book analytics">
              <article class="panel chart-panel distribution-panel rating-panel">
                <header class="chart-heading">
                  <span class="chart-icon" aria-hidden="true">★</span>
                  <div class="chart-heading-copy">
                    <h2 class="chart-title">Ratings distribution</h2>
                    <p class="chart-subtitle">Count of books at each star rating</p>
                  </div>
                  <div class="chart-total">Total books<strong id="rating-chart-total">—</strong></div>
                </header>
                <div id="rating-chart" aria-live="polite"></div>
              </article>
              <article class="panel chart-panel distribution-panel price-panel">
                <header class="chart-heading">
                  <span class="chart-icon" aria-hidden="true">◆</span>
                  <div class="chart-heading-copy">
                    <h2 class="chart-title">Price ranges</h2>
                    <p class="chart-subtitle">Number of books in each GBP price band</p>
                  </div>
                  <div class="chart-total">Total books<strong id="price-chart-total">—</strong></div>
                </header>
                <div id="price-chart" aria-live="polite"></div>
              </article>
              <article class="panel chart-panel">
                <h2 class="chart-title">Highest-rated books</h2>
                <p class="chart-subtitle">Top rating first; ties ordered by title</p>
                <div class="highlight-table-wrap"><table class="highlight-table">
                  <thead><tr><th>#</th><th>Book</th><th>Rating</th><th>Price</th><th>Availability</th></tr></thead>
                  <tbody id="top-rated-list" aria-live="polite"></tbody>
                </table></div>
                <p class="chart-note">Books to Scrape does not publish sales figures. Ratings are shown as a popularity proxy, not verified best-seller data.</p>
              </article>
              <article class="panel chart-panel">
                <h2 class="chart-title">Lowest-priced books</h2>
                <p class="chart-subtitle">The most affordable saved titles</p>
                <div class="highlight-table-wrap"><table class="highlight-table">
                  <thead><tr><th>#</th><th>Book</th><th>Price</th><th>Rating</th><th>Availability</th></tr></thead>
                  <tbody id="low-price-list" aria-live="polite"></tbody>
                </table></div>
              </article>
            </section>
          </main>
          </div>
        </div>
        <script>
          const errorMessage = document.getElementById("error-message");
          const scrapeStatus = document.getElementById("scrape-status");

          function formatPrice(price) {
            return price === null || price === undefined || !Number.isFinite(Number(price))
              ? "—"
              : `£${Number(price).toFixed(2)}`;
          }

          function renderStats(stats) {
            document.getElementById("book-count").textContent = String(stats.total_books);
            document.getElementById("average-rating").textContent =
              stats.average_rating === null ? "—" : Number(stats.average_rating).toFixed(1);
            document.getElementById("average-price").textContent = formatPrice(stats.average_price);
            document.getElementById("min-price-stat").textContent = formatPrice(stats.min_price);
            document.getElementById("max-price-stat").textContent = formatPrice(stats.max_price);
          }

          function svgElement(name, attributes = {}) {
            const element = document.createElementNS("http://www.w3.org/2000/svg", name);
            for (const [key, value] of Object.entries(attributes)) {
              element.setAttribute(key, String(value));
            }
            return element;
          }

          function renderBars(containerId, totalId, totalBooks, items, labelKey, countKey, axisTitle) {
            const container = document.getElementById(containerId);
            container.replaceChildren();
            document.getElementById(totalId).textContent = String(totalBooks);

            const width = 720;
            const height = 330;
            const plot = { left: 76, right: 704, top: 16, bottom: 232 };
            const plotHeight = plot.bottom - plot.top;
            const maximum = Math.max(...items.map((item) => Number(item[countKey]) || 0), 1);
            const roughStep = maximum / 5;
            const magnitude = 10 ** Math.floor(Math.log10(roughStep));
            const fraction = roughStep / magnitude;
            const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * magnitude;
            const axisMaximum = Math.ceil(maximum / step) * step;
            const svg = svgElement("svg", {
              class: "chart-plot",
              viewBox: `0 0 ${width} ${height}`,
              role: "img",
              "aria-label": `${axisTitle} chart, ${totalBooks} books in total`,
              preserveAspectRatio: "xMidYMid meet",
            });
            const title = svgElement("title");
            title.textContent = `${axisTitle} distribution`;
            svg.appendChild(title);

            const defs = svgElement("defs");
            const gradientId = `${containerId}-gradient`;
            const gradient = svgElement("linearGradient", {
              id: gradientId,
              x1: "0",
              x2: "0",
              y1: "0",
              y2: "1",
            });
            gradient.append(
              svgElement("stop", { offset: "0%", "stop-color": "#58bd7b" }),
              svgElement("stop", { offset: "100%", "stop-color": "#25895a" }),
            );
            defs.appendChild(gradient);
            svg.appendChild(defs);

            for (let value = 0; value <= axisMaximum; value += step) {
              const y = plot.bottom - (value / axisMaximum) * plotHeight;
              svg.appendChild(svgElement("line", {
                x1: plot.left,
                x2: plot.right,
                y1: y,
                y2: y,
                class: "chart-gridline",
              }));
              const tick = svgElement("text", {
                x: plot.left - 13,
                y: y + 5,
                "text-anchor": "end",
                class: "chart-tick",
              });
              tick.textContent = String(value);
              svg.appendChild(tick);
            }

            svg.append(
              svgElement("line", {
                x1: plot.left,
                x2: plot.left,
                y1: plot.top,
                y2: plot.bottom,
                class: "chart-axis",
              }),
              svgElement("line", {
                x1: plot.left,
                x2: plot.right,
                y1: plot.bottom,
                y2: plot.bottom,
                class: "chart-axis",
              }),
            );

            const yTitle = svgElement("text", {
              x: 20,
              y: (plot.top + plot.bottom) / 2,
              transform: `rotate(-90 20 ${(plot.top + plot.bottom) / 2})`,
              "text-anchor": "middle",
              class: "chart-axis-title",
            });
            yTitle.textContent = "Number of books";
            svg.appendChild(yTitle);

            const slotWidth = (plot.right - plot.left) / Math.max(items.length, 1);
            items.forEach((item, index) => {
              const countValue = Number(item[countKey]) || 0;
              const barHeight = (countValue / axisMaximum) * plotHeight;
              const center = plot.left + slotWidth * (index + 0.5);
              const barWidth = Math.min(72, slotWidth * 0.58);
              svg.appendChild(svgElement("rect", {
                x: center - barWidth / 2,
                y: plot.bottom - barHeight,
                width: barWidth,
                height: barHeight,
                rx: 7,
                ry: 7,
                class: "chart-bar",
                fill: `url(#${gradientId})`,
              }));

              const count = svgElement("text", {
                x: center,
                y: Math.max(plot.top + 15, plot.bottom - barHeight - 10),
                "text-anchor": "middle",
                class: "chart-count",
              });
              count.textContent = String(countValue);
              svg.appendChild(count);

              const label = svgElement("text", {
                x: center,
                y: plot.bottom + 27,
                "text-anchor": "middle",
                class: "chart-label",
              });
              label.textContent = item[labelKey];
              svg.appendChild(label);
            });

            const xTitle = svgElement("text", {
              x: (plot.left + plot.right) / 2,
              y: 318,
              "text-anchor": "middle",
              class: "chart-axis-title",
            });
            xTitle.textContent = axisTitle;
            svg.appendChild(xTitle);
            container.appendChild(svg);
          }

          function renderHighlights(containerId, books, sortMode) {
            const body = document.getElementById(containerId);
            body.replaceChildren();
            if (!books.length) {
              const row = document.createElement("tr");
              const empty = document.createElement("td");
              empty.className = "chart-empty";
              empty.colSpan = 5;
              empty.textContent = "No books available yet.";
              row.appendChild(empty);
              body.appendChild(row);
              return;
            }
            for (const [index, book] of books.entries()) {
              const row = document.createElement("tr");
              addCell(row, `${index + 1}.`);
              const bookCell = addCell(row, "");
              const bookContent = document.createElement("span");
              bookContent.className = "highlight-book";
              if (book.image_url) {
                const cover = document.createElement("img");
                cover.className = "highlight-cover";
                cover.src = book.image_url;
                cover.alt = "";
                cover.loading = "lazy";
                bookContent.appendChild(cover);
              }
              const link = document.createElement("a");
              link.href = book.url;
              link.target = "_blank";
              link.rel = "noopener noreferrer";
              link.textContent = book.title;
              link.title = book.title;
              bookContent.appendChild(link);
              bookCell.appendChild(bookContent);
              if (sortMode === "rating") {
                const rating = addCell(row, "");
                rating.className = "stars";
                const rank = { one: 1, two: 2, three: 3, four: 4, five: 5 }[
                  String(book.rating).toLowerCase()
                ] || 0;
                rating.textContent = "★".repeat(rank) + "☆".repeat(5 - rank);
                rating.setAttribute("aria-label", `${rank} out of 5 stars`);
              }
              addCell(row, formatPrice(book.price), "price");
              if (sortMode !== "rating") addCell(row, book.rating || "Unknown");
              const status = addCell(row, "");
              const badge = document.createElement("span");
              badge.className = "badge";
              badge.textContent = book.availability || "Unknown";
              if (/out of stock/i.test(badge.textContent)) badge.classList.add("unavailable");
              else if (!/in stock/i.test(badge.textContent)) badge.classList.add("unknown");
              status.appendChild(badge);
              body.appendChild(row);
            }
          }

          function renderAnalytics(analytics, totalBooks) {
            renderBars("rating-chart", "rating-chart-total", totalBooks, analytics.ratings, "rating", "count", "Rating (Stars)");
            renderBars("price-chart", "price-chart-total", totalBooks, analytics.price_ranges, "range", "count", "Price range (GBP)");
            const minPrice = analytics.lowest_priced_books[0];
            if (minPrice) document.getElementById("lowest-price-title").textContent = minPrice.title;
            document.getElementById("highest-price-title").textContent =
              analytics.highest_priced_books[0]?.title || "Across all books";
            renderHighlights("top-rated-list", analytics.top_rated_books, "rating");
            renderHighlights("low-price-list", analytics.lowest_priced_books, "price");
          }

          function addCell(row, value, className) {
            const cell = document.createElement("td");
            if (className) cell.className = className;
            cell.textContent = value;
            row.appendChild(cell);
            return cell;
          }

          async function loadDashboard() {
            errorMessage.hidden = true;
            try {
              const [statsResponse, analyticsResponse] = await Promise.all([
                fetch("/dashboard/stats"),
                fetch("/api/analytics/overview"),
              ]);
              if (!statsResponse.ok || !analyticsResponse.ok) {
                throw new Error("Could not load dashboard data from the API.");
              }
              const [stats, analytics] = await Promise.all([
                statsResponse.json(),
                analyticsResponse.json(),
              ]);
              renderStats(stats);
              renderAnalytics(analytics, stats.total_books);
              document.getElementById("last-updated").textContent =
                new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
              return true;
            } catch (error) {
              errorMessage.textContent = error instanceof Error ? error.message : "Could not load dashboard data.";
              errorMessage.hidden = false;
              return false;
            }
          }

          async function scrapeBooks() {
            const button = document.getElementById("scrape-button");
            button.disabled = true;
            scrapeStatus.hidden = false;
            scrapeStatus.textContent = "Scraping books from the source site...";
            errorMessage.hidden = true;

            try {
              const startResponse = await fetch("/api/scrape?limit=20", { method: "POST" });
              if (!startResponse.ok) {
                throw new Error("Could not start a scrape. Please try again shortly.");
              }
              const { job_id: jobId } = await startResponse.json();
              if (!Number.isInteger(jobId)) {
                throw new Error("The scrape job could not be started.");
              }

              let job;
              do {
                await new Promise((resolve) => setTimeout(resolve, 1500));
                const statusResponse = await fetch(`/api/scrape/status/${jobId}`);
                if (!statusResponse.ok) {
                  throw new Error("Could not check the scrape status. Please refresh and try again.");
                }
                job = await statusResponse.json();
              } while (job.status === "queued" || job.status === "running");

              if (job.status === "failed") {
                throw new Error(job.error_message || "The scrape failed. Please try again.");
              }
              if (!await loadDashboard()) {
                throw new Error("The scrape finished, but dashboard data could not be refreshed.");
              }
              scrapeStatus.textContent = `Scrape ${job.status}: ${job.total_books} books processed. Dashboard updated.`;
            } catch (error) {
              errorMessage.textContent = error instanceof Error ? error.message : "Could not scrape books.";
              errorMessage.hidden = false;
              scrapeStatus.textContent = "Books could not be loaded.";
            } finally {
              button.disabled = false;
            }
          }

          document.getElementById("refresh-button").addEventListener("click", loadDashboard);
          document.getElementById("scrape-button").addEventListener("click", scrapeBooks);
          loadDashboard();
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
    global _last_scrape_at
    if not _scrape_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A scrape is already in progress")

    try:
        now = time.monotonic()
        if (
            _last_scrape_at is not None
            and now - _last_scrape_at < SCRAPE_COOLDOWN_SECONDS
        ):
            retry_after = int(SCRAPE_COOLDOWN_SECONDS - (now - _last_scrape_at)) + 1
            raise HTTPException(
                status_code=429,
                detail="Scraping is temporarily rate-limited; try again shortly",
                headers={"Retry-After": str(retry_after)},
            )
        _last_scrape_at = now

        job = create_scrape_job(db)
        result = run_scrape_job(job.id, limit=limit, scraper=scrape_books, db=db)
        if result["status"] == "failed":
            if result["error_message"] == "Another scrape job is already running":
                raise HTTPException(
                    status_code=429,
                    detail="A scrape is already in progress",
                )
            if result["error_message"] == "Unable to retrieve books from the source website":
                logger.warning("Scraping the configured public source failed")
                raise HTTPException(
                    status_code=502,
                    detail="Unable to retrieve books from the source website",
                )
            raise HTTPException(
                status_code=500,
                detail="Scraped products could not be saved",
            )

        collected = int(result["total_books"] or 0)
        inserted = int(result.get("inserted_books", collected))
        logger.info(
            "Scrape completed collected=%d inserted=%d skipped=%d database=%s",
            collected,
            inserted,
            collected - inserted,
            db.get_bind().dialect.name,
        )
        return {
            "message": f"Collected {collected} products; saved {inserted}",
            "products_collected": collected,
            "products_inserted": inserted,
            "products_skipped": collected - inserted,
            "new_books_saved": inserted,
        }
    finally:
        _scrape_lock.release()


def _reserve_api_scrape_slot() -> None:
    global _last_scrape_at
    if not _scrape_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A scrape is already in progress")
    try:
        now = time.monotonic()
        if (
            _last_scrape_at is not None
            and now - _last_scrape_at < SCRAPE_COOLDOWN_SECONDS
        ):
            retry_after = int(SCRAPE_COOLDOWN_SECONDS - (now - _last_scrape_at)) + 1
            raise HTTPException(
                status_code=429,
                detail="Scraping is temporarily rate-limited; try again shortly",
                headers={"Retry-After": str(retry_after)},
            )
        _last_scrape_at = now
    finally:
        _scrape_lock.release()


@app.post("/api/scrape", status_code=status.HTTP_202_ACCEPTED)
def start_scrape(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=20, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    """Queue a scrape and return its persistent job identifier."""
    _reserve_api_scrape_slot()
    job = create_scrape_job(db)
    background_tasks.add_task(
        run_scrape_job,
        job.id,
        limit=limit,
        scraper=scrape_books,
        db=db,
    )
    return {"job_id": job.id, "status": job.status}


@app.post("/api/scrape/contemporary", status_code=status.HTTP_202_ACCEPTED)
def start_contemporary_scrape(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=1000, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    """Queue a scrape of every book in the Contemporary source category."""
    _reserve_api_scrape_slot()
    job = create_scrape_job(db)

    def scrape_contemporary(limit: int) -> list[dict[str, str | float | None]]:
        return scrape_books(limit=limit, start_url=CONTEMPORARY_URL)

    background_tasks.add_task(
        run_scrape_job,
        job.id,
        limit=limit,
        scraper=scrape_contemporary,
        db=db,
    )
    return {"job_id": job.id, "status": job.status}


@app.get("/api/scrape/status/{job_id}", response_model=ScrapeJobResponse)
def get_scrape_status(
    job_id: int,
    db: Session = Depends(get_db),
) -> ScrapeJob:
    job = db.get(ScrapeJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return job


@app.get("/api/scrape/history", response_model=list[ScrapeJobResponse])
def get_scrape_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ScrapeJob]:
    return list(
        db.scalars(
            select(ScrapeJob)
            .order_by(ScrapeJob.started_at.desc(), ScrapeJob.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Check that the API process and its database are responding."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ok", "database": "connected"}


@app.get("/dashboard/stats", response_model=DashboardStats)
@app.get("/api/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)) -> DashboardStats:
    """Return collection-wide price, rating, and availability summaries."""
    summary = db.execute(
        select(
            func.count(Product.id),
            func.avg(
                case(
                    (func.lower(Product.rating) == "one", 1),
                    (func.lower(Product.rating) == "two", 2),
                    (func.lower(Product.rating) == "three", 3),
                    (func.lower(Product.rating) == "four", 4),
                    (func.lower(Product.rating) == "five", 5),
                    else_=None,
                )
            ),
            func.avg(Product.price),
            func.min(Product.price),
            func.max(Product.price),
            func.sum(
                case(
                    (Product.availability.ilike("%in stock%"), 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (Product.availability.ilike("%out of stock%"), 1),
                    else_=0,
                )
            ),
        )
    ).one()
    (
        total,
        average_rating,
        average_price,
        min_price,
        max_price,
        in_stock,
        out_of_stock,
    ) = summary

    rating_ranks = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
    }
    rated_books = db.execute(
        select(Product.title, Product.rating).where(
            Product.rating.notin_(["", "Unknown"])
        )
    ).all()
    highest_rank = max(
        (rating_ranks.get(rating.lower(), 0) for _, rating in rated_books),
        default=0,
    )
    top_rated = [
        title
        for title, rating in rated_books
        if rating_ranks.get(rating.lower(), 0) == highest_rank and highest_rank > 0
    ]
    top_rated.sort(key=str.casefold)

    return DashboardStats(
        total_books=total,
        in_stock=in_stock or 0,
        out_of_stock=out_of_stock or 0,
        availability_unknown=total - (in_stock or 0) - (out_of_stock or 0),
        average_rating=average_rating,
        average_price=average_price,
        min_price=min_price,
        max_price=max_price,
        top_rating=({1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}.get(highest_rank)),
        top_rated_count=len(top_rated),
        top_rated_titles=top_rated[:5],
    )


@app.get("/api/analytics/overview")
def get_analytics_overview(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return category, rating, and price distributions plus useful book lists."""
    category_rows = db.execute(
        select(Product.category, func.count(Product.id))
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc(), Product.category.asc())
    ).all()
    categories = [
        {"category": category or "Uncategorized", "count": count}
        for category, count in category_rows
    ]

    rank = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    rating_rank = case(
        (func.lower(Product.rating) == "one", 1),
        (func.lower(Product.rating) == "two", 2),
        (func.lower(Product.rating) == "three", 3),
        (func.lower(Product.rating) == "four", 4),
        (func.lower(Product.rating) == "five", 5),
        else_=0,
    )
    rating_counts = {
        str(rating).lower(): count
        for rating, count in db.execute(
            select(Product.rating, func.count(Product.id)).group_by(Product.rating)
        ).all()
    }
    ratings = [
        {
            "rating": f"{rank[name]} star" if rank[name] == 1 else f"{rank[name]} stars",
            "count": rating_counts.get(name, 0),
        }
        for name in ("one", "two", "three", "four", "five")
    ]

    price_band = case(
        (Product.price < 10, "Under £10"),
        (Product.price < 20, "£10–£19.99"),
        (Product.price < 30, "£20–£29.99"),
        (Product.price < 50, "£30–£49.99"),
        else_="£50 and over",
    )
    price_counts = dict(
        db.execute(
            select(price_band, func.count(Product.id)).group_by(price_band)
        ).all()
    )
    price_ranges = [
        {"range": label, "count": price_counts.get(label, 0)}
        for label in (
            "Under £10",
            "£10–£19.99",
            "£20–£29.99",
            "£30–£49.99",
            "£50 and over",
        )
    ]

    def book_summary(product: Product) -> dict[str, object]:
        return {
            "id": product.id,
            "title": product.title,
            "price": product.price,
            "rating": product.rating,
            "category": product.category,
            "availability": product.availability,
            "image_url": product.image_url,
            "url": product.url,
        }

    top_rated = db.scalars(
        select(Product)
        .where(func.lower(Product.rating).in_(tuple(rank)))
        .order_by(rating_rank.desc(), Product.title.asc())
        .limit(5)
    ).all()
    lowest_priced = db.scalars(
        select(Product).order_by(Product.price.asc(), Product.title.asc()).limit(5)
    ).all()
    highest_priced = db.scalars(
        select(Product).order_by(Product.price.desc(), Product.title.asc()).limit(5)
    ).all()
    return {
        "categories": categories,
        "ratings": ratings,
        "price_ranges": price_ranges,
        "top_rated_books": [book_summary(product) for product in top_rated],
        "lowest_priced_books": [book_summary(product) for product in lowest_priced],
        "highest_priced_books": [book_summary(product) for product in highest_priced],
    }


@app.get("/api/analytics/prices")
def get_price_analytics(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    ranked_history = (
        select(
            PriceHistory.book_id.label("book_id"),
            PriceHistory.price.label("price"),
            PriceHistory.recorded_at.label("recorded_at"),
            func.row_number()
            .over(
                partition_by=PriceHistory.book_id,
                order_by=(PriceHistory.recorded_at.desc(), PriceHistory.id.desc()),
            )
            .label("rank"),
            func.min(PriceHistory.price)
            .over(partition_by=PriceHistory.book_id)
            .label("lowest"),
            func.max(PriceHistory.price)
            .over(partition_by=PriceHistory.book_id)
            .label("highest"),
            func.avg(PriceHistory.price)
            .over(partition_by=PriceHistory.book_id)
            .label("average"),
            func.count(PriceHistory.id)
            .over(partition_by=PriceHistory.book_id)
            .label("observations"),
        )
        .subquery()
    )
    latest = select(ranked_history).where(ranked_history.c.rank == 1).subquery()
    previous = select(ranked_history).where(ranked_history.c.rank == 2).subquery()
    total = db.scalar(select(func.count()).select_from(Product)) or 0
    average_price, min_price, max_price = db.execute(
        select(func.avg(Product.price), func.min(Product.price), func.max(Product.price))
    ).one()
    rows = db.execute(
        select(
            Product,
            latest.c.recorded_at.label("observed_at"),
            latest.c.lowest,
            latest.c.highest,
            latest.c.average,
            latest.c.observations,
            previous.c.price.label("previous_price"),
        )
        .outerjoin(latest, latest.c.book_id == Product.id)
        .outerjoin(previous, previous.c.book_id == Product.id)
        .order_by(Product.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = []
    for (
        product,
        observed_at,
        lowest,
        highest,
        average,
        observations,
        previous_price,
    ) in rows:
        price_change = (
            product.price - previous_price if previous_price is not None else None
        )
        percentage_change = (
            price_change / previous_price * 100
            if price_change is not None and previous_price
            else None
        )
        items.append(
            {
                "book_id": product.id,
                "title": product.title,
                "current_price": product.price,
                "previous_observed_price": previous_price,
                "price_change": price_change,
                "percentage_change": percentage_change,
                "lowest_historical_price": lowest,
                "highest_historical_price": highest,
                "average_historical_price": average,
                "last_observed_at": observed_at,
                "history_observation_count": observations or 0,
            }
        )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "average_current_price": average_price,
        "min_current_price": min_price,
        "max_current_price": max_price,
        "books": items,
    }


@app.get("/api/analytics/ratings")
def get_rating_analytics(db: Session = Depends(get_db)) -> dict[str, object]:
    rank = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    rows = db.execute(
        select(Product.rating, func.count(Product.id))
        .group_by(Product.rating)
    ).all()
    ratings = [
        {"rating": rating, "count": count}
        for rating, count in sorted(
            rows,
            key=lambda row: rank.get(str(row[0]).lower(), 0),
        )
    ]
    rated = [
        (rank[str(rating).lower()], count)
        for rating, count in rows
        if str(rating).lower() in rank
    ]
    total_rated = sum(count for _, count in rated)
    average = (
        sum(score * count for score, count in rated) / total_rated
        if total_rated
        else None
    )
    return {"total_rated_books": total_rated, "average_rating": average, "ratings": ratings}


@app.get("/api/analytics/availability")
def get_availability_analytics(db: Session = Depends(get_db)) -> dict[str, object]:
    rows = db.execute(
        select(Product.availability, func.count(Product.id))
        .group_by(Product.availability)
        .order_by(Product.availability)
    ).all()
    return {
        "total_books": sum(count for _, count in rows),
        "availability": [
            {"status": availability, "count": count}
            for availability, count in rows
        ],
    }


@app.get(
    "/api/books/{book_id}/price-history",
    response_model=list[PriceHistoryResponse],
)
def get_book_price_history(
    book_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[PriceHistory]:
    if db.get(Product, book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return list(
        db.scalars(
            select(PriceHistory)
            .where(PriceHistory.book_id == book_id)
            .order_by(PriceHistory.recorded_at.desc(), PriceHistory.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


def _filtered_products(
    db: Session,
    search: str | None,
    min_price: float | None,
    max_price: float | None,
    availability: str | None,
    category: str | None = None,
    rating: str | None = None,
) -> Select[tuple[Product]]:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=422,
            detail="min_price must be less than or equal to max_price",
        )

    query = select(Product)
    if search and search.strip():
        query = query.where(Product.title.ilike(f"%{search.strip()}%"))
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)
    if availability and availability.strip():
        query = query.where(Product.availability.ilike(f"%{availability.strip()}%"))
    if category and category.strip():
        if category.strip().casefold() == "uncategorized":
            query = query.where(Product.category.is_(None))
        else:
            query = query.where(Product.category.ilike(category.strip()))
    if rating and rating.strip():
        query = query.where(Product.rating.ilike(rating.strip()))
    return query


@app.get("/products", response_model=ProductPage)
def get_products(
    search: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    availability: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=200),
    rating: str | None = Query(default=None, max_length=20),
    sort_by: str = Query(default="id", pattern="^(id|title|price|rating)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ProductPage:
    """List filtered products with a total count and offset-based pagination."""
    query = _filtered_products(
        db, search, min_price, max_price, availability, category, rating
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rating_rank = case(
        (func.lower(Product.rating) == "one", 1),
        (func.lower(Product.rating) == "two", 2),
        (func.lower(Product.rating) == "three", 3),
        (func.lower(Product.rating) == "four", 4),
        (func.lower(Product.rating) == "five", 5),
        else_=0,
    )
    sort_column = {
        "id": Product.id,
        "title": Product.title,
        "price": Product.price,
        "rating": rating_rank,
    }[sort_by]
    ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
    products = db.scalars(
        query.order_by(ordering, Product.title.asc()).offset(offset).limit(limit)
    ).all()
    return ProductPage(total=total, limit=limit, offset=offset, products=products)


@app.get("/api/books", response_model=ProductPage)
def get_api_books(
    search: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    availability: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=200),
    rating: str | None = Query(default=None, max_length=20),
    sort_by: str = Query(
        default="id",
        pattern="^(id|title|price|rating|availability|created_at|updated_at)$",
    ),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ProductPage:
    query = _filtered_products(
        db, search, min_price, max_price, availability, category, rating
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rating_rank = case(
        (func.lower(Product.rating) == "one", 1),
        (func.lower(Product.rating) == "two", 2),
        (func.lower(Product.rating) == "three", 3),
        (func.lower(Product.rating) == "four", 4),
        (func.lower(Product.rating) == "five", 5),
        else_=0,
    )
    sort_column = {
        "id": Product.id,
        "title": Product.title,
        "price": Product.price,
        "rating": rating_rank,
        "availability": Product.availability,
        "created_at": Product.created_at,
        "updated_at": Product.updated_at,
    }[sort_by]
    ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
    products = db.scalars(query.order_by(ordering, Product.id).offset(offset).limit(limit)).all()
    return ProductPage(total=total, limit=limit, offset=offset, products=products)


@app.get("/api/books/{book_id}", response_model=ProductResponse)
def get_api_book(
    book_id: int,
    db: Session = Depends(get_db),
) -> Product:
    book = db.get(Product, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@app.get("/products/export.csv")
@app.get("/api/export/csv")
def export_products_csv(
    search: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    availability: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=200),
    rating: str | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
) -> Response:
    """Download all products matching the supplied filters as a CSV file."""
    query = _filtered_products(
        db, search, min_price, max_price, availability, category, rating
    )
    products = db.scalars(query.order_by(Product.id)).all()

    def safe_cell(value: str | None) -> str:
        cell = value or ""
        if cell.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
            return f"'{cell}"
        return cell

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "title",
            "category",
            "price",
            "availability",
            "rating",
            "product_url",
            "image_url",
        ]
    )
    for product in products:
        writer.writerow(
            [
                safe_cell(product.title),
                safe_cell(product.category),
                f"{product.price:.2f}",
                safe_cell(product.availability),
                safe_cell(product.rating),
                safe_cell(product.url),
                safe_cell(product.image_url),
            ]
        )

    return Response(
        content=f"\ufeff{output.getvalue()}",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="books.csv"'},
    )


@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
) -> Product:
    """Return one product, or 404 when its database ID does not exist."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/books")
def get_books(
    search: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    availability: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
) -> list[dict[str, int | str | float | None]]:
    """Return saved books, optionally matching a title and inclusive price bounds."""
    query = _filtered_products(db, search, min_price, max_price, availability)
    books = db.scalars(query.order_by(Product.id)).all()
    return [
        {
            "id": book.id,
            "title": book.title,
            "price": book.price,
            "availability": book.availability,
            "rating": book.rating,
            "url": book.url,
            "image_url": book.image_url,
        }
        for book in books
    ]
