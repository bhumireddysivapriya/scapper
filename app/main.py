import csv
from io import StringIO
import logging
import threading
import time

import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Select, case, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db, initialize_database
from app.models import Product
from app.schemas import DashboardStats, ProductPage, ProductResponse
from app.scraper import scrape_books

logger = logging.getLogger(__name__)
initialize_database()

SCRAPE_COOLDOWN_SECONDS = 30
_scrape_lock = threading.Lock()
_last_scrape_at: float | None = None

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
          .sidebar {
            position: fixed; inset: 0 auto 0 0; z-index: 3; display: flex;
            flex-direction: column; width: 240px; padding: 18px 14px;
            background: #fff; border-right: 1px solid #e6ebe7;
          }
          .sidebar-brand {
            display: flex; align-items: center; gap: 10px; padding: 0 4px 18px;
            border-bottom: 1px solid #edf0ed;
          }
          .brand-mark {
            display: grid; place-items: center; width: 36px; height: 36px;
            border-radius: 10px; color: #fff; background: #286343; font-size: 19px;
          }
          .brand-name { font-size: 15px; font-weight: 750; line-height: 1.15; }
          .side-nav { display: grid; gap: 5px; padding-top: 16px; }
          .side-nav a {
            display: flex; align-items: center; gap: 11px; padding: 10px 11px;
            border-radius: 9px; color: #66746b; font-size: 13px;
            text-decoration: none; transition: background .15s, color .15s;
          }
          .side-nav a:hover, .side-nav a.active { color: #20583a; background: #eaf5ee; }
          .side-icon { width: 18px; text-align: center; font-size: 15px; }
          .side-divider { height: 1px; margin: 12px 4px; background: #edf0ed; }
          .sidebar-promo {
            margin-top: auto; padding: 16px 14px; border: 1px solid #e0eee4;
            border-radius: 14px; color: #42604c; background: #f0f8f2;
            font-size: 12px; line-height: 1.5;
          }
          .promo-art { margin-bottom: 7px; font-size: 27px; }
          .sidebar-promo strong { display: block; margin-bottom: 4px; color: #286343; font-size: 14px; }
          .workspace { min-height: 100vh; margin-left: 240px; }
          .topbar {
            position: sticky; top: 0; z-index: 2; display: flex;
            align-items: center; justify-content: space-between; gap: 20px;
            min-height: 64px; padding: 10px 24px;
            background: #fff; border-bottom: 1px solid #e6ebe7;
          }
          .global-search {
            display: flex; align-items: center; gap: 9px; width: min(440px, 55%);
            min-height: 40px; padding: 0 12px; color: #7a867d;
            border: 1px solid #e1e7e2; border-radius: 9px; background: #fbfcfb;
          }
          .global-search input {
            width: 100%; min-height: 36px; padding: 0; border: 0;
            background: transparent; outline: 0; font-size: 12px;
          }
          .top-actions { display: flex; align-items: center; gap: 17px; }
          .top-link { color: #66746b; font-size: 12px; text-decoration: none; }
          .profile {
            display: flex; align-items: center; gap: 8px; color: #506056;
            font-size: 12px; font-weight: 650; text-decoration: none;
          }
          .avatar {
            display: grid; place-items: center; width: 30px; height: 30px;
            border-radius: 50%; color: #fff; background: #286343; font-weight: 750;
          }
          main { width: 100%; max-width: 1500px; margin: 0 auto; padding: 26px 28px 34px; }
          .dashboard-title {
            margin: 0 0 16px; font-size: clamp(24px, 3vw, 32px);
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
            display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px; margin-bottom: 14px;
          }
          .card, .panel {
            background: #fff; border: 1px solid #e6ebe7; border-radius: 14px;
            box-shadow: 0 3px 12px rgb(25 50 35 / 3%);
          }
          .card {
            position: relative; min-height: 94px; padding: 15px 13px 13px 54px;
            overflow: hidden;
          }
          .card-icon {
            position: absolute; top: 14px; left: 13px; display: grid;
            place-items: center; width: 34px; height: 34px; border-radius: 10px;
            color: #286343; background: #e1f4e8; font-size: 18px;
          }
          .card:nth-child(2) { background: linear-gradient(120deg, #fffdf6, #fff9e9); }
          .card:nth-child(2) .card-icon { color: #d18400; background: #fff0c8; }
          .card:nth-child(3) { background: linear-gradient(120deg, #f8fbff, #f0f6ff); }
          .card:nth-child(3) .card-icon, .card:nth-child(8) .card-icon { color: #286bc4; background: #e1edff; }
          .card:nth-child(4), .card:nth-child(7) { background: linear-gradient(120deg, #fffafa, #fff2f2); }
          .card:nth-child(4) .card-icon, .card:nth-child(7) .card-icon { color: #d44b4b; background: #ffe3e3; }
          .card:nth-child(5) { background: linear-gradient(120deg, #fdfaff, #f7f1ff); }
          .card:nth-child(5) .card-icon { color: #8c4ed1; background: #eee0ff; }
          .card:nth-child(6) { background: linear-gradient(120deg, #f9fff9, #eff9f0); }
          .card:nth-child(6) .card-icon { color: #288346; background: #dff6e4; }
          .card-label { color: #748078; font-size: 13px; }
          .card-value { margin-top: 7px; font-size: 22px; font-weight: 750; }
          .card-detail {
            margin-top: 4px; color: #748078; font-size: 10px;
            line-height: 1.45; overflow-wrap: anywhere;
          }
          .top-rated-value { font-size: 15px; line-height: 1.25; }
          .top-stars { color: #e79912; letter-spacing: 1px; }
          .panel { overflow: hidden; margin-bottom: 13px; }
          .filters {
            display: flex; align-items: end; gap: 12px; flex-wrap: wrap;
            padding: 14px 16px; border-bottom: 1px solid #edf0ed;
          }
          .field { display: grid; gap: 6px; }
          .field.search { flex: 1 1 240px; }
          .field.price { width: 120px; }
          label { color: #69756d; font-size: 11px; font-weight: 650; }
          input {
            width: 100%; min-height: 38px; padding: 0 11px; color: #17211b;
            background: #fff; border: 1px solid #dfe6e0; outline: none;
          }
          select { min-height: 38px; }
          button { min-height: 38px; border-radius: 8px; font-size: 12px; }
          input:focus { border-color: #43805b; box-shadow: 0 0 0 3px #43805b20; }
          .secondary {
            color: #355542; background: #edf4ef; border: 1px solid #dce9df;
          }
          .secondary:hover { background: #e2eee5; }
          .table-head {
            display: flex; align-items: center; justify-content: space-between;
            gap: 12px; padding: 13px 17px; color: #34443a; font-size: 13px;
          }
          .table-actions { display: flex; align-items: center; gap: 12px; }
          .download-button {
            display: inline-flex; align-items: center; justify-content: center;
            min-height: 34px; padding: 0 11px; border: 1px solid #dce9df;
            border-radius: 8px; color: #355542; background: #edf4ef;
            font-size: 11px; font-weight: 650; text-decoration: none; white-space: nowrap;
          }
          .download-button:hover { background: #e2eee5; }
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
            .sidebar { width: 205px; }
            .workspace { margin-left: 205px; }
            main { padding-right: 20px; padding-left: 20px; }
            .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
            .card { padding-left: 48px; }
            .card-icon { left: 9px; width: 31px; height: 31px; }
          }
          @media (max-width: 760px) {
            .sidebar { position: static; width: auto; padding: 10px 14px; border-right: 0; border-bottom: 1px solid #e6ebe7; }
            .sidebar-brand { padding-bottom: 9px; border: 0; }
            .side-nav { display: flex; gap: 4px; overflow-x: auto; padding-top: 2px; }
            .side-nav a { flex: 0 0 auto; padding: 8px 10px; font-size: 11px; }
            .side-divider, .sidebar-promo { display: none; }
            .workspace { margin-left: 0; }
            .topbar { position: static; min-height: 56px; padding: 8px 14px; }
            .global-search { width: min(330px, 60%); }
            .top-link { display: none; }
            main { padding: 18px 14px 25px; }
            .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
            .card { min-height: 90px; padding: 13px 9px 10px 46px; }
            .card-icon { top: 12px; left: 8px; width: 30px; height: 30px; }
            .card-label { font-size: 11px; }
            .card-value { font-size: 19px; }
            .top-rated-value { font-size: 13px; }
            .filters { gap: 9px; padding: 12px; }
            .field.search { flex-basis: 100%; }
            .field.price { flex: 1 1 100px; width: auto; }
            .table-head { padding: 12px; }
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
          <aside class="sidebar">
            <a class="sidebar-brand" href="/" aria-label="BookShelf home">
              <span class="brand-mark" aria-hidden="true">▮▮</span>
              <span class="brand-name">BookShelf</span>
            </a>
            <nav class="side-nav" aria-label="Main navigation">
              <a class="active" href="#dashboard"><span class="side-icon" aria-hidden="true">⌂</span>Dashboard</a>
              <a href="#books"><span class="side-icon" aria-hidden="true">◉</span>Scrape Books</a>
              <span class="side-divider" aria-hidden="true"></span>
              <a href="/docs"><span class="side-icon" aria-hidden="true">▣</span>API Docs</a>
              <a href="/books"><span class="side-icon" aria-hidden="true">‹›</span>JSON API</a>
            </nav>
            <div class="sidebar-promo">
              <div class="promo-art" aria-hidden="true">📚</div>
              <strong>Build your own library</strong>
              Collect, explore and analyze books effortlessly.
            </div>
          </aside>
          <div class="workspace">
          <header class="topbar">
            <label class="global-search" for="global-search">
              <span aria-hidden="true">⌕</span>
              <input id="global-search" type="search" placeholder="Search books, titles, or authors…" autocomplete="off">
            </label>
            <div class="top-actions">
              <a class="top-link" href="/docs" aria-label="Open API documentation">♧</a>
              <a class="profile" href="/" aria-label="BookShelf dashboard">
                <span class="avatar" aria-hidden="true">B</span> BookShelf <span aria-hidden="true">⌄</span>
              </a>
            </div>
          </header>
          <main id="dashboard">
            <h1 class="dashboard-title">Dashboard</h1>
            <section class="cards" id="analytics" aria-label="Collection statistics" aria-live="polite">
              <article class="card">
                <span class="card-icon" aria-hidden="true">▤</span>
                <div class="card-label">Total books</div>
                <div class="card-value" id="book-count">—</div>
                <div class="card-detail">In the saved collection</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">★</span>
                <div class="card-label">Top-rated book</div>
                <div class="card-value top-rated-value" id="top-rated-title">—</div>
                <div class="card-detail top-stars" id="top-rated-stars" aria-label="Top rating">☆☆☆☆☆</div>
                <div class="card-detail" id="top-rated-detail">Loading rating data…</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">◇</span>
                <div class="card-label">Average price</div>
                <div class="card-value" id="average-price">—</div>
                <div class="card-detail">Across all saved books</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">▥</span>
                <div class="card-label">Lowest price</div>
                <div class="card-value" id="min-price-stat">—</div>
                <div class="card-detail">Price range minimum</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">↗</span>
                <div class="card-label">Highest price</div>
                <div class="card-value" id="max-price-stat">—</div>
                <div class="card-detail">Price range maximum</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">▣</span>
                <div class="card-label">In stock</div>
                <div class="card-value" id="stock-count">—</div>
                <div class="card-detail">Books marked available</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">⊠</span>
                <div class="card-label">Out of stock</div>
                <div class="card-value" id="out-of-stock-count">—</div>
                <div class="card-detail">Books marked unavailable</div>
              </article>
              <article class="card">
                <span class="card-icon" aria-hidden="true">?</span>
                <div class="card-label">Availability unknown</div>
                <div class="card-value" id="unknown-stock-count">—</div>
                <div class="card-detail">Missing or unrecognized stock status</div>
              </article>
            </section>
            <section class="panel" id="filters" aria-label="Book filters">
              <form class="filters" id="filter-form" aria-label="Filter books">
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
                <div class="field">
                  <label for="availability">Availability</label>
                  <select id="availability" name="availability">
                    <option value="">All</option>
                    <option value="In stock">In stock</option>
                    <option value="Out of stock">Out of stock</option>
                  </select>
                </div>
                <button type="submit">▼ &nbsp; Apply filters</button>
                <button class="secondary" id="clear-button" type="button">Clear all</button>
              </form>
            </section>
            <section class="panel" id="books" aria-label="Book collection">
              <p class="error" id="error-message" role="alert" hidden></p>
              <div class="table-head" aria-live="polite">
                <strong><span aria-hidden="true">▮▮ &nbsp;</span>Scraped books</strong>
                <div class="table-actions">
                  <button class="scrape-button" id="scrape-button" type="button">↻ &nbsp; Scrape latest books</button>
                  <span id="result-label">Loading books…</span>
                  <a class="download-button" id="download-csv" href="/products/export.csv" download>
                    ↓ &nbsp; Download CSV
                  </a>
                </div>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr><th>#</th><th aria-label="Cover image"></th><th>Title</th><th>Price</th><th>Availability</th><th>Rating</th><th>Action</th></tr>
                  </thead>
                  <tbody id="book-rows"></tbody>
                </table>
                <div class="message" id="empty-message" hidden></div>
              </div>
              <div class="pagination">
                <span id="pagination-label">Loading books…</span>
                <nav class="page-controls" id="page-controls" aria-label="Book pages"></nav>
              </div>
            </section>
          </main>
          </div>
        </div>
        <script>
          const form = document.getElementById("filter-form");
          const rows = document.getElementById("book-rows");
          const errorMessage = document.getElementById("error-message");
          const emptyMessage = document.getElementById("empty-message");
          const scrapeButton = document.getElementById("scrape-button");
          const downloadCsv = document.getElementById("download-csv");
          const pageSize = 10;
          let currentOffset = 0;
          let currentTotal = 0;
          let searchTimer;

          function formatPrice(price) {
            return price === null || price === undefined || !Number.isFinite(Number(price))
              ? "—"
              : `£${Number(price).toFixed(2)}`;
          }

          function renderStats(stats) {
            document.getElementById("book-count").textContent = String(stats.total_books);
            document.getElementById("top-rated-title").textContent =
              stats.top_rated_titles.length ? stats.top_rated_titles[0] : "No ratings";
            document.getElementById("top-rated-detail").textContent = stats.top_rating
              ? `${stats.top_rating} stars · ${stats.top_rated_count} ${stats.top_rated_count === 1 ? "book" : "books"}`
              : "No rated books in the collection";
            const ratingValue = { One: 1, Two: 2, Three: 3, Four: 4, Five: 5 }[stats.top_rating] || 0;
            document.getElementById("top-rated-stars").textContent =
              "★".repeat(ratingValue) + "☆".repeat(5 - ratingValue);
            document.getElementById("average-price").textContent = formatPrice(stats.average_price);
            document.getElementById("min-price-stat").textContent = formatPrice(stats.min_price);
            document.getElementById("max-price-stat").textContent = formatPrice(stats.max_price);
            document.getElementById("stock-count").textContent = String(stats.in_stock);
            document.getElementById("out-of-stock-count").textContent = String(stats.out_of_stock);
            document.getElementById("unknown-stock-count").textContent =
              String(stats.availability_unknown);
          }

          function addCell(row, value, className) {
            const cell = document.createElement("td");
            if (className) cell.className = className;
            cell.textContent = value;
            row.appendChild(cell);
            return cell;
          }

          function renderBooks(books) {
            rows.replaceChildren();

            for (const [index, book] of books.entries()) {
              const row = document.createElement("tr");
              addCell(row, String(currentOffset + index + 1));
              const coverCell = addCell(row, "");
              if (book.image_url) {
                const cover = document.createElement("img");
                cover.className = "cover";
                cover.src = book.image_url;
                cover.alt = `Cover of ${book.title || "book"}`;
                cover.loading = "lazy";
                cover.onerror = () => {
                  const placeholder = document.createElement("span");
                  placeholder.className = "cover-placeholder";
                  placeholder.setAttribute("aria-hidden", "true");
                  placeholder.textContent = "📖";
                  cover.replaceWith(placeholder);
                };
                coverCell.appendChild(cover);
              } else {
                const placeholder = document.createElement("span");
                placeholder.className = "cover-placeholder";
                placeholder.setAttribute("aria-hidden", "true");
                placeholder.textContent = "📖";
                coverCell.appendChild(placeholder);
              }
              addCell(row, book.title || "Untitled", "book-title");
              const price = Number(book.price);
              addCell(row, Number.isFinite(price) ? `£${price.toFixed(2)}` : "Unknown", "price");

              const availability = addCell(row, "");
              const badge = document.createElement("span");
              badge.className = "badge";
              badge.textContent = book.availability || "Unknown";
              if (/out of stock/i.test(badge.textContent)) {
                badge.classList.add("unavailable");
              } else if (!/in stock/i.test(badge.textContent)) {
                badge.classList.add("unknown");
              }
              availability.appendChild(badge);

              const rating = (book.rating || "Unknown").toLowerCase();
              const ratingValue = { one: 1, two: 2, three: 3, four: 4, five: 5 }[rating] || 0;
              const ratingCell = addCell(row, "");
              ratingCell.className = "rating";
              const stars = document.createElement("span");
              stars.className = "stars";
              stars.setAttribute("aria-label", `${ratingValue} out of 5 stars`);
              stars.textContent = "★".repeat(ratingValue) + "☆".repeat(5 - ratingValue);
              ratingCell.appendChild(stars);
              const productCell = addCell(row, "");
              const productLink = document.createElement("a");
              productLink.className = "action-link";
              productLink.href = book.url;
              productLink.target = "_blank";
              productLink.rel = "noopener noreferrer";
              productLink.textContent = "View ↗";
              productCell.appendChild(productLink);

              rows.appendChild(row);
            }

            const first = currentTotal === 0 ? 0 : currentOffset + 1;
            const last = Math.min(currentOffset + books.length, currentTotal);
            document.getElementById("result-label").textContent =
              `${currentTotal} ${currentTotal === 1 ? "book" : "books"}`;
            document.getElementById("pagination-label").textContent =
              `Showing ${first}–${last} of ${currentTotal} books`;
            renderPagination();
            emptyMessage.hidden = books.length !== 0;
            emptyMessage.textContent = books.length
              ? ""
              : "No books found. Try changing your filters or scrape the latest books.";
          }

          function renderPagination() {
            const controls = document.getElementById("page-controls");
            controls.replaceChildren();
            const pageCount = Math.ceil(currentTotal / pageSize);
            const currentPage = Math.floor(currentOffset / pageSize);
            const addPageButton = (label, page, accessibleLabel, disabled = false, current = false) => {
              const button = document.createElement("button");
              button.type = "button";
              button.className = `page-button${current ? " current" : ""}`;
              button.textContent = label;
              button.setAttribute("aria-label", accessibleLabel);
              if (current) button.setAttribute("aria-current", "page");
              button.disabled = disabled;
              button.addEventListener("click", () => {
                currentOffset = page * pageSize;
                loadBooks();
              });
              controls.appendChild(button);
            };
            addPageButton("‹", Math.max(0, currentPage - 1), "Previous page", currentPage === 0);
            const start = Math.max(0, Math.min(currentPage - 2, pageCount - 5));
            const end = Math.min(pageCount, start + 5);
            for (let page = start; page < end; page += 1) {
              addPageButton(String(page + 1), page, `Page ${page + 1}`, false, page === currentPage);
            }
            addPageButton("›", Math.min(pageCount - 1, currentPage + 1), "Next page",
              pageCount === 0 || currentPage >= pageCount - 1);
          }

          function updateCsvDownloadUrl() {
            const params = new URLSearchParams(new FormData(form));
            for (const [key, value] of [...params.entries()]) {
              if (!value.trim()) params.delete(key);
            }
            downloadCsv.href = `/products/export.csv?${params.toString()}`;
          }

          async function loadBooks() {
            errorMessage.hidden = true;
            document.getElementById("books").setAttribute("aria-busy", "true");
            const params = new URLSearchParams(new FormData(form));
            for (const [key, value] of [...params.entries()]) {
              if (!value.trim()) params.delete(key);
            }
            updateCsvDownloadUrl();
            params.set("limit", String(pageSize));
            params.set("offset", String(currentOffset));
            document.getElementById("result-label").textContent = "Loading books…";
            try {
              const [statsResponse, booksResponse] = await Promise.all([
                fetch("/dashboard/stats"),
                fetch(`/products?${params.toString()}`),
              ]);
              if (!statsResponse.ok || !booksResponse.ok) {
                throw new Error("Could not load dashboard data from the API.");
              }
              const [stats, page] = await Promise.all([
                statsResponse.json(),
                booksResponse.json(),
              ]);
              currentTotal = page.total;
              renderStats(stats);
              renderBooks(page.products);
            } catch (error) {
              errorMessage.textContent = error instanceof Error ? error.message : "Could not load dashboard data.";
              errorMessage.hidden = false;
              document.getElementById("result-label").textContent = "Unable to load books";
            } finally {
              document.getElementById("books").setAttribute("aria-busy", "false");
            }
          }

          form.addEventListener("submit", (event) => {
            event.preventDefault();
            currentOffset = 0;
            document.getElementById("global-search").value = document.getElementById("search").value;
            updateCsvDownloadUrl();
            loadBooks();
          });
          document.getElementById("clear-button").addEventListener("click", () => {
            form.reset();
            document.getElementById("global-search").value = "";
            currentOffset = 0;
            updateCsvDownloadUrl();
            loadBooks();
          });
          document.getElementById("global-search").addEventListener("input", (event) => {
            document.getElementById("search").value = event.target.value;
            currentOffset = 0;
            updateCsvDownloadUrl();
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(loadBooks, 250);
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

        try:
            books = scrape_books(limit=limit)
        except requests.RequestException as exc:
            logger.warning("Scraping the configured public source failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="Unable to retrieve books from the source website",
            ) from exc

        records = [
            {
                "title": str(item["title"]),
                "price": float(item["price"]),
                "availability": str(item["availability"]),
                "rating": str(item["rating"]),
                "url": str(item["url"]),
                "image_url": str(item["image_url"]) if item.get("image_url") else None,
            }
            for item in books
        ]
        try:
            if records:
                existing_urls = set(
                    db.scalars(
                        select(Product.url).where(
                            Product.url.in_([record["url"] for record in records])
                        )
                    ).all()
                )
                statement = sqlite_insert(Product).values(records)
                statement = statement.on_conflict_do_update(
                    index_elements=[Product.url],
                    set_={"image_url": statement.excluded.image_url},
                    where=statement.excluded.image_url.is_not(None),
                )
                result = db.execute(statement)
                inserted = len({record["url"] for record in records} - existing_urls)
                db.commit()
            else:
                inserted = 0
        except SQLAlchemyError as exc:
            db.rollback()
            logger.exception("Could not save scraped products")
            raise HTTPException(
                status_code=500,
                detail="Scraped products could not be saved",
            ) from exc

        return {
            "message": f"Collected {len(books)} products; saved {inserted}",
            "products_collected": len(books),
            "products_inserted": inserted,
            "products_skipped": len(books) - inserted,
            "new_books_saved": inserted,
        }
    finally:
        _scrape_lock.release()


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
def get_dashboard_stats(db: Session = Depends(get_db)) -> DashboardStats:
    """Return collection-wide price, rating, and availability summaries."""
    summary = db.execute(
        select(
            func.count(Product.id),
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
    total, average_price, min_price, max_price, in_stock, out_of_stock = summary

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
        average_price=average_price,
        min_price=min_price,
        max_price=max_price,
        top_rating=({1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}.get(highest_rank)),
        top_rated_count=len(top_rated),
        top_rated_titles=top_rated[:5],
    )


def _filtered_products(
    db: Session,
    search: str | None,
    min_price: float | None,
    max_price: float | None,
    availability: str | None,
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
    return query


@app.get("/products", response_model=ProductPage)
def get_products(
    search: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    availability: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ProductPage:
    """List filtered products with a total count and offset-based pagination."""
    query = _filtered_products(db, search, min_price, max_price, availability)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    products = db.scalars(
        query.order_by(Product.id).offset(offset).limit(limit)
    ).all()
    return ProductPage(total=total, limit=limit, offset=offset, products=products)


@app.get("/products/export.csv")
def export_products_csv(
    search: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    availability: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
) -> Response:
    """Download all products matching the supplied filters as a CSV file."""
    query = _filtered_products(db, search, min_price, max_price, availability)
    products = db.scalars(query.order_by(Product.id)).all()

    def safe_cell(value: str | None) -> str:
        cell = value or ""
        if cell.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
            return f"'{cell}"
        return cell

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ["title", "price", "availability", "rating", "product_url", "image_url"]
    )
    for product in products:
        writer.writerow(
            [
                safe_cell(product.title),
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
