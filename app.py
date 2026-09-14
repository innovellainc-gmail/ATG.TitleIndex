from __future__ import annotations

import csv
import base64
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin

import pandas as pd
import streamlit as st


PORTAL_URL = "https://donaana.nm.publicsearch.us/"
DATABASE_PATH = Path(os.environ.get("DONA_ANA_DATABASE", "dona_ana_records.db"))
DOCUMENT_DIRECTORY = Path(os.environ.get("DONA_ANA_DOCUMENTS", "document_images"))
DEFAULT_DEPARTMENT = "Real Property"

LOGGER = logging.getLogger("dona_ana_indexer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

METADATA_FIELDS = [
    "Legal Description", "Section", "Town", "Subdivision", "Lot", "Range", "Block",
    "County", "Grantor", "Grantee", "Volume", "Page",
    "Instrument Date", "Instrument Number", "Township", "Range or Block (S-T-R)",
    "Abstract Number", "Survey", "Quarter Call", "Book Type", "Instrument Type",
    "Instrument Type Alias", "Subdivision Alias", "Lot (Sub)", "Block (Sub)",
    "Acres", "File Date", "Instrument Type Group", "Prior Reference Instrument Number",
    "Prior Reference Volume", "Prior Reference Page", "State", "APN #", "Street Address",
    "City (Address)", "State (Address)", "Zip (Address)", "Tract Description (City Block)",
]
STORAGE_FIELDS = [
    "local_file_path", "original_document_file", "source_url", "indexed_at", "record_hash", "scrape_error"
]
ALL_FIELDS = METADATA_FIELDS + STORAGE_FIELDS


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "Instrument Number": ("inst number", "instrument no", "instrument #", "document number", "doc number"),
    "Range or Block (S-T-R)": ("range", "block", "range or block", "s t r", "str"),
    "APN #": ("apn", "parcel number", "parcel id", "tax id"),
    "Lot (Sub)": ("lot", "lot sub"),
    "Block (Sub)": ("block", "block sub"),
    "City (Address)": ("city", "address city"),
    "State (Address)": ("state", "address state"),
    "Zip (Address)": ("zip", "zip code", "postal code"),
    "Tract Description (City Block)": ("tract description", "city block", "tract"),
}


class RecordDatabase:
    """SQLite persistence with short-lived connections, safe for worker threads."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialise()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialise(self) -> None:
        columns = ["record_id INTEGER PRIMARY KEY AUTOINCREMENT"]
        columns.extend(f"{_quote_identifier(field)} TEXT" for field in ALL_FIELDS)
        columns.extend([
            'UNIQUE("record_hash")',
            'CHECK("record_hash" IS NOT NULL)',
        ])
        with self.connect() as connection:
            connection.execute(f"CREATE TABLE IF NOT EXISTS indexed_documents ({', '.join(columns)})")
            existing_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(indexed_documents)").fetchall()
            }
            for field in ALL_FIELDS:
                if field not in existing_columns:
                    connection.execute(f"ALTER TABLE indexed_documents ADD COLUMN {_quote_identifier(field)} TEXT")
            connection.execute(
                'UPDATE indexed_documents SET "source_url" = ? '
                'WHERE "source_url" LIKE \'file://%\'',
                [PORTAL_URL],
            )
            connection.execute(
                'CREATE INDEX IF NOT EXISTS idx_indexed_documents_instrument '
                'ON indexed_documents("Instrument Number")'
            )
            connection.execute(
                'CREATE INDEX IF NOT EXISTS idx_indexed_documents_address '
                'ON indexed_documents("Street Address")'
            )

    def upsert(self, record: dict[str, Any]) -> None:
        values = {field: str(record.get(field, "") or "") for field in ALL_FIELDS}
        values["indexed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        fields = list(values)
        placeholders = ", ".join("?" for _ in fields)
        assignments = ", ".join(
            f"{_quote_identifier(field)}=excluded.{_quote_identifier(field)}"
            for field in fields if field != "record_hash"
        )
        sql = (
            f"INSERT INTO indexed_documents ({', '.join(_quote_identifier(field) for field in fields)}) "
            f"VALUES ({placeholders}) ON CONFLICT(record_hash) DO UPDATE SET {assignments}"
        )
        with self.connect() as connection:
            connection.execute(sql, [values[field] for field in fields])

    def list_records(self, search: str = "", limit: int = 500) -> pd.DataFrame:
        with self.connect() as connection:
            if search.strip():
                terms = f"%{search.strip()}%"
                where = " OR ".join(f"{_quote_identifier(field)} LIKE ?" for field in METADATA_FIELDS)
                rows = connection.execute(
                    f"SELECT * FROM indexed_documents WHERE {where} ORDER BY record_id DESC LIMIT ?",
                    [terms] * len(METADATA_FIELDS) + [limit],
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM indexed_documents ORDER BY record_id DESC LIMIT ?", [limit]
                ).fetchall()
        return pd.DataFrame([dict(row) for row in rows])

    def count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM indexed_documents").fetchone()[0])

    def clear_records(self) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM indexed_documents")

    def get_record(self, record_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM indexed_documents WHERE record_hash = ?", [record_hash]
            ).fetchone()
        return dict(row) if row else None

    def set_document_path(self, instrument_number: str, file_path: Path) -> None:
        with self.connect() as connection:
            connection.execute(
                'UPDATE indexed_documents SET "local_file_path" = ?, "original_document_file" = ?, '
                '"source_url" = CASE WHEN "source_url" IS NULL OR "source_url" = "" '
                'OR "source_url" LIKE \'file://%\' THEN ? ELSE "source_url" END '
                'WHERE "Instrument Number" = ?',
                [str(file_path), str(file_path), PORTAL_URL, instrument_number],
            )

    def csv_bytes(self, search: str = "") -> bytes:
        frame = self.list_records(search, limit=100000)
        output = io.StringIO()
        frame.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
        return output.getvalue().encode("utf-8-sig")


@dataclass(frozen=True)
class SearchOptions:
    start_date: date
    end_date: date
    search_term: str
    department: str
    website_url: str = PORTAL_URL
    username: str = ""
    password: str = ""
    headed: bool = False
    throttle_seconds: float = 0.25


class PortalScraper:
    """Defensive Playwright adapter for the public records portal."""

    def __init__(self, options: SearchOptions, database: RecordDatabase, progress: Callable[[str], None]) -> None:
        self.options = options
        self.database = database
        self.progress = progress
        self.document_directory = DOCUMENT_DIRECTORY
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._page = None
        self._total_records = 0
        self._cart_records = 0

    def configure_controls(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.pause_event = pause_event

    def _checkpoint(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            self.progress("Paused")
            time.sleep(0.2)
        if self.stop_event.is_set():
            raise RuntimeError("Execution stopped by the user.")

    def _throttle(self) -> None:
        if self.options.throttle_seconds > 0:
            time.sleep(self.options.throttle_seconds)

    def _wait_for_network_idle(self, page: Any, timeout: int = 30000) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception as error:
            LOGGER.info("Network idle wait timed out; continuing with DOM readiness checks: %s", error)
            self.progress("Portal is still loading background requests; continuing when required controls are ready")

    def run(self) -> None:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Playwright is not installed. Run: pip install -r requirements.txt") from error

        self.document_directory.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not self.options.headed)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            self._page = page
            page.set_default_timeout(15000)
            json_payloads: list[Any] = []

            def capture_json(response: Any) -> None:
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    return
                try:
                    payload = response.json()
                    if isinstance(payload, (dict, list)):
                        json_payloads.append(payload)
                except Exception:
                    return

            page.on("response", capture_json)
            try:
                self._open_search(page)
                api_records = self._records_from_json(json_payloads)
                if api_records:
                    self.progress(f"Found {len(api_records)} records in a JSON response; enriching details")
                self._paginate_and_add_to_cart(page, api_records)
                self._checkout_cart(page)
            except PlaywrightTimeoutError as error:
                LOGGER.error("Playwright timed out during portal automation: %s", error)
                self.progress(f"Portal automation timed out while waiting for a control: {error}")
                raise
            except Exception:
                try:
                    screenshot = self._failure_screenshot("automation")
                    page.screenshot(path=str(screenshot), full_page=True)
                    self.progress(f"Failure screenshot captured: {screenshot}")
                except Exception:
                    LOGGER.exception("Unable to capture automation failure screenshot")
                raise
            finally:
                context.close()
                browser.close()

    def _open_search(self, page: Any) -> None:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        self._checkpoint()
        self.progress("Opening the Doña Ana County records portal")
        page.goto(self.options.website_url, wait_until="domcontentloaded")
        self._wait_for_network_idle(page)
        self._sign_in(page)
        self._select_search_type(page)
        start_date_input = page.get_by_role("textbox", name="Starting Recorded Date")
        end_date_input = page.get_by_role("textbox", name="Ending Recorded Date")
        start_date_input.wait_for(state="visible", timeout=30000)
        end_date_input.wait_for(state="visible", timeout=30000)
        for date_input, date_value in (
            (start_date_input, self.options.start_date.strftime("%m/%d/%Y")),
            (end_date_input, self.options.end_date.strftime("%m/%d/%Y")),
        ):
            date_input.click()
            date_input.press("Control+A")
            date_input.press("Backspace")
            date_input.fill(date_value)
            date_input.press("Tab")
        search_button = page.locator(
            "button[type='submit'][aria-label='Search'][data-testid='searchSubmitButton']"
        )
        search_button.wait_for(state="visible", timeout=30000)
        search_button.click()
        self._wait_for_network_idle(page)
        try:
            page.locator("table tbody tr, [role='row']").first.wait_for(state="attached", timeout=30000)
        except PlaywrightTimeoutError:
            self.progress("Search completed without result rows")

    def _select_search_type(self, page: Any) -> None:
        candidates = [
            page.get_by_text(re.compile(r"search index.*full text.*ocr", re.I)).first,
            page.get_by_role("tab", name=re.compile(r"search index.*full text.*ocr", re.I)).first,
            page.locator("input[type='radio'][value*='full' i], input[type='radio'][id*='ocr' i]").first,
        ]
        for candidate in candidates:
            if candidate.count() and candidate.is_visible():
                try:
                    if candidate.get_attribute("aria-selected") != "true":
                        candidate.click()
                    break
                except Exception:
                    continue
        index_only = [
            page.get_by_role("tab", name=re.compile(r"index only", re.I)).first,
            page.get_by_text(re.compile(r"index only", re.I)).first,
        ]
        for candidate in index_only:
            if candidate.count() and candidate.is_visible():
                try:
                    candidate.click()
                    break
                except Exception:
                    continue

    def _sign_in(self, page: Any) -> None:
        sign_in_link = page.get_by_role("link", name=re.compile(r"^sign\s*in$", re.I)).last
        if not sign_in_link.count():
            sign_in_link = page.get_by_text(re.compile(r"^sign\s*in$", re.I)).last
        if not sign_in_link.count() or not sign_in_link.is_visible():
            navigation_menu = page.locator("[controls='nav-menu']").first
            if not navigation_menu.count():
                navigation_menu = page.locator("button[controls='nav-menu'], [aria-controls='nav-menu']").first
            if navigation_menu.count() and navigation_menu.is_visible():
                navigation_menu.click()
                sign_in_link = page.get_by_role("link", name=re.compile(r"^sign\s*in$", re.I)).last
                if not sign_in_link.count():
                    sign_in_link = page.get_by_text(re.compile(r"^sign\s*in$", re.I)).last
        if not sign_in_link.count() or not sign_in_link.is_visible():
            raise RuntimeError("Could not find the Sign In link on the records portal.")

        sign_in_link.click()
        self._wait_for_network_idle(page)
        page.get_by_role("heading", name=re.compile(r"^sign\s*in$", re.I)).wait_for(
            state="visible", timeout=30000
        )
        self._fill_sign_in_field(page, "email", self.options.username)
        self._fill_sign_in_field(page, "password", self.options.password)

        sign_in_button = page.get_by_role("button", name=re.compile(r"^sign\s*in$", re.I)).last
        if not sign_in_button.count():
            sign_in_button = page.locator("button[type='submit'], input[type='submit']").last
        if not sign_in_button.count() or not sign_in_button.is_visible():
            raise RuntimeError("Could not find the Sign In button on the portal sign-in page.")
        sign_in_button.click()
        self._wait_for_network_idle(page)
        quick_search = page.get_by_role("tab", name=re.compile(r"^quick\s*search$", re.I)).first
        if not quick_search.count():
            quick_search = page.get_by_text(re.compile(r"^quick\s*search$", re.I)).first
        quick_search.wait_for(state="visible", timeout=30000)

    def _fill_sign_in_field(self, page: Any, field: str, value: str) -> None:
        accessible_name = re.compile(r"^email$", re.I) if field == "email" else re.compile(r"^password$", re.I)
        role_locator = page.get_by_role("textbox", name=accessible_name).last
        if role_locator.count() and role_locator.is_visible() and role_locator.is_editable():
            role_locator.fill(value)
            return

        selectors = (
            [
                "input[type='email']", "input[autocomplete='username']", "input[name='email' i]",
                "input[id='email' i]", "input[placeholder*='email' i]", "input[name*='user' i]",
                "input[id*='user' i]",
            ] if field == "email" else [
                "input[type='password']", "input[autocomplete='current-password']", "input[name='password' i]",
                "input[id='password' i]", "input[placeholder*='password' i]", "input[name*='pass' i]",
                "input[id*='pass' i]",
            ]
        )
        for selector in selectors:
            locator = page.locator(selector).last
            if locator.count() and locator.is_visible() and locator.is_editable():
                locator.fill(value)
                return
        labels = re.compile(r"email|user ?name", re.I) if field == "email" else re.compile(r"password", re.I)
        locator = page.get_by_label(labels).last
        if locator.count() and locator.is_visible() and locator.is_editable():
            locator.fill(value)
            return
        raise RuntimeError(f"Could not find the Sign In page {field} input box.")

    def _fill_first(self, page: Any, selectors: list[str], value: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                locator.fill(value)
                return
        raise RuntimeError(f"Could not find a search field for value {value!r}.")

    def _select_department(self, page: Any) -> None:
        selects = page.locator("select")
        for index in range(selects.count()):
            select = selects.nth(index)
            options = select.locator("option").all_text_contents()
            if any(self.options.department.lower() in option.lower() for option in options):
                matching = next(option for option in options if self.options.department.lower() in option.lower())
                select.select_option(label=matching)
                return
        department = page.get_by_text(self.options.department, exact=True).first
        if department.count() and department.is_visible():
            department.click()
            option = page.get_by_role("option", name=re.compile(re.escape(self.options.department), re.I)).first
            if option.count():
                option.click()

    def _paginate_and_add_to_cart(self, page: Any, api_records: list[dict[str, Any]]) -> None:
        page_number = 1
        seen: set[str] = set()
        while True:
            self._checkpoint()
            self.progress(f"Reading results page {page_number}")
            rows = self._table_rows(page)
            if not rows and page_number == 1 and api_records:
                rows = [(record, None) for record in api_records]
            if not rows and page_number == 1:
                self.progress("No result rows were found")
            self._total_records += len(rows)
            self.progress(f"Found {self._total_records} total records")
            for row_number, (row, detail_url) in enumerate(rows):
                self._checkpoint()
                if self._add_result_to_cart(page, row_number):
                    self._cart_records += 1
                    self.progress(f"Added {self._cart_records} of {self._total_records} records to cart")
                record = dict(row)
                if detail_url:
                    record.update(self._read_detail(page, detail_url))
                self._store_record(record, detail_url)
            next_link = self._next_link(page)
            if next_link is None:
                break
            marker = next_link.get_attribute("href") or next_link.inner_text()
            if marker in seen:
                break
            seen.add(marker)
            next_link.click()
            self._wait_for_network_idle(page)
            page_number += 1

    def _add_result_to_cart(self, page: Any, row_number: int) -> bool:
        results_table = page.locator("table").filter(
            has=page.locator("caption").filter(
                has_text=re.compile(r"Search results table for Real Property", re.I)
            )
        )
        results_table.wait_for(state="visible", timeout=30000)
        rows = results_table.locator("tbody").locator("tr")
        if row_number >= rows.count():
            self.progress("Could not locate the result row action menu; record metadata was retained")
            return False
        row = rows.nth(row_number)
        for attempt in range(3):
            try:
                self._checkpoint()
                menu = row.locator(
                    "button.a11y-menu__control[data-tourid='menu__control']"
                ).last
                menu.wait_for(state="visible", timeout=10000)
                menu.click()
                menu_item = page.locator(
                    "button[data-testid='documentAction']"
                ).filter(has_text=re.compile(r"^add\s+to\s+cart$", re.I)).last
                menu_item.wait_for(state="visible", timeout=5000)
                menu_item.click()
                modal = page.locator("[role='dialog']").filter(
                    has_text=re.compile(r"add\s+to\s+cart", re.I)
                ).last
                if not modal.count():
                    modal = page.locator(".modal, [class*='modal' i]").filter(
                        has_text=re.compile(r"add\s+to\s+cart", re.I)
                    ).last
                modal.wait_for(state="visible", timeout=10000)
                add_button = modal.locator("button").filter(
                    has_text=re.compile(r"^add(?:\s+to\s+cart)?$", re.I)
                ).last
                add_button.wait_for(state="visible", timeout=10000)
                add_button.click()
                modal.wait_for(state="hidden", timeout=15000)
                next_row = rows.nth(row_number + 1)
                if row_number + 1 < rows.count():
                    next_row.wait_for(state="visible", timeout=30000)
                    next_row.locator(
                        "button.a11y-menu__control[data-tourid='menu__control']"
                    ).wait_for(state="visible", timeout=30000)
                self._throttle()
                return True
            except Exception as error:
                if attempt == 2:
                    self.progress(f"Cart add failed for result {row_number + 1}: {error}")
                    try:
                        page.screenshot(path=str(self._failure_screenshot("cart_add")), full_page=True)
                    except Exception:
                        pass
        return False

    def _checkout_cart(self, page: Any) -> None:
        if self._cart_records == 0:
            self.progress("No records were added to cart; checkout skipped")
            return
        self._checkpoint()
        self.progress("Opening cart")
        cart = page.locator("p[data-testid='cart'].css-ye3715").first
        if not cart.count() or not cart.is_visible():
            navigation_menu = page.locator("[controls='nav-menu'], button[controls='nav-menu'], [aria-controls='nav-menu']").first
            if navigation_menu.count() and navigation_menu.is_visible():
                navigation_menu.click()
                cart = page.locator("p[data-testid='cart'].css-ye3715").first
        cart.wait_for(state="visible", timeout=30000)
        pages_before_click = set(page.context.pages)
        cart.click()
        cart_page = page
        cart_navigation_deadline = time.monotonic() + 30000 / 1000
        while time.monotonic() < cart_navigation_deadline:
            new_pages = [candidate for candidate in page.context.pages if candidate not in pages_before_click]
            if new_pages:
                cart_page = new_pages[-1]
                break
            time.sleep(0.1)
        cart_page.wait_for_load_state("domcontentloaded", timeout=30000)
        self._wait_for_network_idle(cart_page)
        shopping_cart = cart_page.get_by_text(re.compile(r"shopping cart", re.I)).first
        if shopping_cart.count():
            shopping_cart.wait_for(state="visible", timeout=300000)
        order = cart_page.locator("a[data-testid='orderButton'].css-1iwc97t").first
        order.wait_for(state="visible", timeout=300000)
        order.click()
        cart_page.wait_for_load_state("domcontentloaded", timeout=30000)
        self.progress("Order placed; downloading original documents")
        package_path = self.document_directory / "original_documents_package"
        package_path.mkdir(parents=True, exist_ok=True)
        cart_pdf_files = self._download_cart_pdfs(cart_page, package_path)
        download_buttons = cart_page.locator("button.css-kcz2et")
        download_buttons.first.wait_for(state="attached", timeout=300000)
        download_button = self._wait_for_download_all_button(cart_page, download_buttons)
        if not download_button.is_enabled():
            raise RuntimeError("Download All Documents button is rendered but disabled.")
        with cart_page.expect_download(timeout=150000) as download_info:
            download_button.click()
        download = download_info.value
        archive_path = package_path / (download.suggested_filename or "documents_package.zip")
        download.save_as(str(archive_path))
        extracted_files: list[str] = []
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    target = Path(member.filename)
                    if target.is_absolute() or ".." in target.parts:
                        continue
                    destination = package_path / target
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("wb") as output:
                        output.write(source.read())
                    extracted_files.append(str(destination))
        else:
            extracted_files.append(str(archive_path))
        manifest = {
            "package": "ORIGINAL_DOCUMENT_IMAGES",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": self.options.website_url,
            "files": sorted(set(extracted_files + cart_pdf_files)),
        }
        (package_path / "ORIGINAL_DOCUMENT_IMAGES.manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        self.progress(f"Downloaded {len(set(extracted_files + cart_pdf_files))} original document files")

    @staticmethod
    def _wait_for_download_all_button(page: Any, buttons: Any) -> Any:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            for index in range(buttons.count()):
                try:
                    candidate = buttons.nth(index)
                    if not candidate.is_visible():
                        continue
                    text = (candidate.inner_text() or "").strip().lower()
                    aria_label = (candidate.get_attribute("aria-label") or "").lower()
                    title_text = " ".join(candidate.locator("title").all_text_contents()).lower()
                    accessible_text = " ".join((text, aria_label, title_text))
                    if "download all documents" in accessible_text and "download pdf" not in accessible_text:
                        return candidate
                except Exception:
                    continue
            time.sleep(0.25)
        raise RuntimeError("Download All Documents button was not rendered on the Cart page.")

    def _download_cart_pdfs(self, cart_page: Any, package_path: Path) -> list[str]:
        download_buttons = cart_page.locator("button.css-kcz2et").filter(
            has_text=re.compile(r"download\s+pdf", re.I)
        )
        download_buttons.first.wait_for(state="attached", timeout=300000)
        records = self.database.list_records(limit=100000).to_dict("records")
        record_by_instrument = {
            str(record.get("Instrument Number", "")).strip(): record
            for record in records
            if str(record.get("Instrument Number", "")).strip()
        }
        saved_files: list[str] = []
        for index in range(download_buttons.count()):
            self._checkpoint()
            button = download_buttons.nth(index)
            button.wait_for(state="visible", timeout=300000)
            text = ""
            for level in range(1, 7):
                ancestor = button.locator("xpath=" + "/.." * level).first
                if not ancestor.count():
                    continue
                candidate_text = ancestor.inner_text()
                if any(instrument in candidate_text for instrument in record_by_instrument):
                    text = candidate_text
                    break
            if not text:
                text = button.locator("xpath=..").inner_text()
            record = next(
                (candidate for instrument, candidate in record_by_instrument.items() if instrument in text),
                None,
            )
            if record is None:
                self.progress(f"Could not match cart PDF {index + 1} to an instrument number")
                continue
            instrument = str(record.get("Instrument Number", "")).strip()
            document_type = str(
                record.get("Instrument Type") or record.get("Book Type") or "Document"
            ).strip() or "Document"
            safe_name = re.sub(r"[<>:\"/\\|?*]+", "_", f"{instrument}_{document_type}").strip()
            destination = package_path / f"{safe_name}.PDF"
            with cart_page.expect_download(timeout=150000) as download_info:
                button.click()
            download = download_info.value
            download.save_as(str(destination))
            self.database.set_document_path(instrument, destination)
            saved_files.append(str(destination))
            self.progress(f"Downloaded PDF for instrument {instrument}")
        return saved_files

    def _failure_screenshot(self, step: str) -> Path:
        directory = self.document_directory / "failure_screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{step}.png"

    def _table_rows(self, page: Any) -> list[tuple[dict[str, str], str | None]]:
        tables = page.locator("table").filter(
            has=page.locator("caption").filter(
                has_text=re.compile(r"Search results table for Real Property", re.I)
            )
        )
        for table_index in range(tables.count()):
            table = tables.nth(table_index)
            headers = [_normalise(text) for text in table.locator("thead th").all_text_contents()]
            body_rows = table.locator("tbody tr")
            if not headers:
                first_row = table.locator("tr").first
                headers = [_normalise(text) for text in first_row.locator("th").all_text_contents()]
            if not headers or body_rows.count() == 0:
                continue
            result: list[tuple[dict[str, str], str | None]] = []
            for index in range(body_rows.count()):
                row = body_rows.nth(index)
                cells = row.locator("td").all_text_contents()
                values = {header: cells[position].strip() for position, header in enumerate(headers) if position < len(cells)}
                instrument_cell = row.locator("td.css-tlx2m5").first
                if instrument_cell.count():
                    instrument_number = instrument_cell.inner_text().strip()
                    if instrument_number:
                        values["Instrument Number"] = instrument_number
                link = row.locator("a[href]").first
                result.append((self._map_fields(values), link.get_attribute("href") if link.count() else None))
            return result
        return []

    def _read_detail(self, page: Any, detail_url: str) -> dict[str, str]:
        detail = page.context.new_page()
        detail.set_default_timeout(12000)
        try:
            detail.goto(urljoin(PORTAL_URL, detail_url), wait_until="domcontentloaded")
            self._wait_for_network_idle(detail, timeout=25000)
            values: dict[str, str] = {}
            for label in detail.locator("dt, th, .label, [class*='label' i]").all_text_contents():
                key = _normalise(label)
                if not key:
                    continue
                candidate = detail.locator("dt, th, .label, [class*='label' i]").filter(has_text=label).first
                value_locator = candidate.locator("xpath=following-sibling::*[1]")
                if value_locator.count():
                    values[key] = value_locator.inner_text().strip()
            if not values:
                text = detail.locator("body").inner_text()
                for line in text.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        values[_normalise(key)] = value.strip()
            record = self._map_fields(values)
            record["local_file_path"] = self._download_document(detail, detail_url, record)
            return record
        except Exception as error:
            LOGGER.warning("Unable to read detail page %s: %s", detail_url, error)
            return {"scrape_error": str(error)}
        finally:
            detail.close()

    def _download_document(self, page: Any, detail_url: str, record: dict[str, str]) -> str:
        links = page.locator("a[href]")
        for index in range(links.count()):
            link = links.nth(index)
            href = link.get_attribute("href") or ""
            label = (link.inner_text() or "").lower()
            if not re.search(r"pdf|image|document|download|instrument|view", f"{href} {label}", re.I):
                continue
            url = urljoin(detail_url, href)
            suffix = Path(url.split("?", 1)[0]).suffix.lower() or ".bin"
            digest = self._record_hash(record, detail_url)
            destination = self.document_directory / f"{digest}{suffix}"
            try:
                response = page.request.get(url, timeout=30000)
                if response.ok:
                    destination.write_bytes(response.body())
                    return str(destination)
            except Exception as error:
                LOGGER.warning("Document download failed for %s: %s", url, error)
        return ""

    def _store_record(self, record: dict[str, str], detail_url: str | None) -> None:
        mapped = {field: record.get(field, "") for field in METADATA_FIELDS + STORAGE_FIELDS}
        mapped["source_url"] = urljoin(PORTAL_URL, detail_url or "")
        mapped["record_hash"] = self._record_hash(mapped, detail_url or "")
        self.database.upsert(mapped)

    @staticmethod
    def _record_hash(record: dict[str, Any], source: str) -> str:
        identity = "|".join(str(record.get(field, "")) for field in (
            "Instrument Number", "Volume", "Page", "Instrument Date", "Grantor", "Grantee"
        )) + "|" + source
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _map_fields(values: dict[str, Any]) -> dict[str, str]:
        normalised = {_normalise(str(key)): str(value).strip() for key, value in values.items()}
        mapped: dict[str, str] = {}
        for field in METADATA_FIELDS:
            candidates = (_normalise(field),) + tuple(_normalise(alias) for alias in FIELD_ALIASES.get(field, ()))
            for candidate in candidates:
                if candidate in normalised and normalised[candidate]:
                    mapped[field] = normalised[candidate]
                    break
        mapped.update(PortalScraper._parse_legal_description(mapped.get("Legal Description", "")))
        return mapped

    @staticmethod
    def _parse_legal_description(description: str) -> dict[str, str]:
        derived = {field: "" for field in ("Section", "Town", "Subdivision", "Lot", "Range", "Block")}
        if not description or description.strip().upper() == "N/A":
            return derived
        aliases = {
            "section": "Section",
            "town": "Town",
            "township": "Town",
            "subdivision": "Subdivision",
            "lot": "Lot",
            "range": "Range",
            "block": "Block",
        }
        for segment in description.split(","):
            if ":" not in segment:
                continue
            label, value = segment.split(":", 1)
            field = aliases.get(_normalise(label))
            value = value.strip()
            if field and value and value.upper() != "N/A":
                derived[field] = value
        return derived

    @staticmethod
    def _next_link(page: Any) -> Any | None:
        candidates = [
            page.get_by_role("link", name=re.compile(r"next", re.I)).last,
            page.get_by_role("button", name=re.compile(r"next", re.I)).last,
            page.locator("a[rel='next'], button[aria-label*='next' i]").last,
        ]
        for candidate in candidates:
            if candidate.count() and candidate.is_visible() and candidate.is_enabled():
                disabled = candidate.get_attribute("aria-disabled") == "true"
                if not disabled:
                    return candidate
        return None

    @staticmethod
    def _records_from_json(payloads: Iterable[Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for payload in payloads:
            candidates = payload if isinstance(payload, list) else payload.get("results", payload.get("data", [])) if isinstance(payload, dict) else []
            if isinstance(candidates, list):
                for item in candidates:
                    if isinstance(item, dict) and any(_normalise(field) in {_normalise(key) for key in item} for field in METADATA_FIELDS):
                        records.append(PortalScraper._map_fields(item))
        return records


def _start_worker(options: SearchOptions, database: RecordDatabase) -> None:
    status = st.session_state["index_status"]
    status.setdefault("logs", [])
    status.setdefault("total_records", 0)
    status.setdefault("cart_records", 0)
    status.update(running=True, error="", message="Starting browser")
    stop_event = threading.Event()
    pause_event = threading.Event()
    st.session_state["execution_controls"] = {"stop": stop_event, "pause": pause_event}

    def report(message: str) -> None:
        status["message"] = message
        status.setdefault("logs", []).append(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        status["logs"] = status["logs"][-100:]
        found_match = re.search(r"Found (\d+) total records", message)
        cart_match = re.search(r"Added (\d+) of (\d+) records", message)
        if found_match:
            status["total_records"] = int(found_match.group(1))
        if cart_match:
            status["cart_records"] = int(cart_match.group(1))

    def work() -> None:
        try:
            scraper = PortalScraper(options, database, report)
            scraper.configure_controls(stop_event, pause_event)
            scraper.run()
            status["message"] = "Indexing complete"
        except Exception as error:
            LOGGER.exception("Indexing failed")
            status["error"] = str(error)
            status["message"] = "Indexing failed"
        finally:
            status["running"] = False

    thread = threading.Thread(target=work, name="dona-ana-indexer", daemon=True)
    st.session_state["index_thread"] = thread
    thread.start()


def _render_document_preview(record: dict[str, Any]) -> None:
    document_path = Path(str(record.get("local_file_path", "")))
    if not document_path.is_file():
        st.warning("The original document was not saved locally for this record.")
        if record.get("source_url"):
            st.link_button("Open source record", str(record["source_url"]))
        return

    suffix = document_path.suffix.lower()
    st.caption(f"Saved original: {document_path}")
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff"}:
        st.image(str(document_path), caption="Original document image", width="stretch")
    elif suffix == ".pdf":
        encoded = base64.b64encode(document_path.read_bytes()).decode("ascii")
        st.html(
            f'<iframe src="data:application/pdf;base64,{encoded}" width="100%" height="760" '
            'style="border:1px solid #d7dce5;border-radius:8px;"></iframe>',
        )
    else:
        st.info(f"The saved document format ({suffix or 'unknown'}) cannot be previewed in the browser.")
    st.download_button(
        "Download original document",
        data=document_path.read_bytes(),
        file_name=document_path.name,
        mime="application/pdf" if suffix == ".pdf" else "application/octet-stream",
        key=f"download-{record['record_hash']}",
    )


def _render_record_details(database: RecordDatabase, frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("No indexed records match the current search.")
        return

    labels: list[str] = []
    for _, row in frame.iterrows():
        instrument = str(row.get("Instrument Number", "") or "No instrument number")
        grantor = str(row.get("Grantor", "") or "Unknown grantor")
        grantee = str(row.get("Grantee", "") or "Unknown grantee")
        labels.append(f"{instrument} | {grantor} -> {grantee}")
    selected_label = st.selectbox("Select a record to inspect", labels, key="selected_record_label")
    selected_index = labels.index(selected_label)
    selected_hash = str(frame.iloc[selected_index]["record_hash"])
    record = database.get_record(selected_hash)
    if record is None:
        st.error("The selected record is no longer available in the local database.")
        return

    metadata_columns = st.columns(2)
    midpoint = (len(METADATA_FIELDS) + 1) // 2
    for column, fields in zip(metadata_columns, (METADATA_FIELDS[:midpoint], METADATA_FIELDS[midpoint:])):
        with column:
            for field in fields:
                value = str(record.get(field, "") or "").strip()
                if value:
                    st.markdown(f"**{field}**  \n{value}")

    st.divider()
    st.subheader("Original document")
    _render_document_preview(record)


def _render_table(database: RecordDatabase, search: str) -> None:
    frame = database.list_records(search)
    if frame.empty:
        st.info("No indexed records match the current search.")
    else:
        display_frame = frame[
            [
                "Instrument Number", "Legal Description", "Section", "Town", "Subdivision",
                "Lot", "Range", "Block", "Instrument Date", "Grantor", "Grantee",
                "Street Address", "City (Address)", "State (Address)", "Zip (Address)",
                "source_url",
            ]
        ].rename(columns={"source_url": "Original document URL"})
        st.dataframe(
            display_frame,
            width="stretch",
            height=420,
            hide_index=True,
            column_config={
                "Instrument Number": st.column_config.TextColumn("INST NUMBER"),
                "Original document URL": st.column_config.LinkColumn(
                    "Original document URL", display_text="Open portal document"
                ),
            },
        )
    return frame


def main() -> None:
    st.set_page_config(page_title="Doña Ana Records Indexer", layout="wide")
    database = RecordDatabase()
    if "index_status" not in st.session_state:
        st.session_state["index_status"] = {
            "running": False,
            "message": "Idle",
            "error": "",
            "logs": [],
            "total_records": 0,
            "cart_records": 0,
        }
    status = st.session_state["index_status"]
    status.setdefault("logs", [])
    status.setdefault("total_records", 0)
    status.setdefault("cart_records", 0)

    st.title("Doña Ana County Public Records Indexer")
    st.caption("Search the county portal, inspect captured metadata, and review saved original documents.")
    with st.sidebar:
        st.header("Index search")
        date_range = st.date_input(
            "Instrument date range",
            value=(date(1978, 1, 1), date(1978, 1, 7)),
            min_value=date(1600, 1, 1),
            max_value=date.today(),
            format="MM/DD/YYYY",
            help="Choose the inclusive instrument-date range to send to the county portal.",
        )
        search_term = st.text_input("Grantor / Grantee", placeholder="Optional name or organization")
        department = st.text_input("Department", value=DEFAULT_DEPARTMENT)
        website_url = st.text_input("Target website", value=PORTAL_URL)
        username = st.text_input("Website username", value="innovella.inc@gmail.com", type="default", help="Leave blank if the portal does not require login.")
        password = st.text_input("Website password", value="!nn0v3ll@.ATG", type="password")
        headed = st.checkbox("Show browser window", value=False, help="Run Chromium visibly for troubleshooting.")
        throttle = st.number_input("Delay between cart actions (seconds)", min_value=0.0, max_value=10.0, value=0.25, step=0.05)
        start = st.button("Start Indexing", type="primary", width="stretch", disabled=status["running"])
        if start:
            if not isinstance(date_range, tuple) or len(date_range) != 2:
                st.error("Choose both a start and end date.")
                st.stop()
            start_date, end_date = date_range
            if start_date > end_date:
                st.error("Start date must be on or before end date.")
            elif not website_url.strip().startswith(("http://", "https://")):
                st.error("Target website must be an HTTP or HTTPS URL.")
            else:
                status.update(total_records=0, cart_records=0, logs=[])
                _start_worker(
                    SearchOptions(
                        start_date, end_date, search_term, department, website_url.strip(),
                        username, password, headed, float(throttle),
                    ),
                    database,
                )
                st.rerun()
        if st.button("Clear indexed results", width="stretch", disabled=status["running"]):
            database.clear_records()
            status.update(message="Indexed results cleared", error="", logs=[], total_records=0, cart_records=0)
            st.rerun()
        if status["running"]:
            controls = st.session_state.get("execution_controls", {})
            pause_event = controls.get("pause")
            stop_event = controls.get("stop")
            paused = bool(pause_event and pause_event.is_set())
            if st.button("Resume" if paused else "Pause", icon=":material/play_arrow:" if paused else ":material/pause:", width="stretch"):
                if pause_event:
                    pause_event.clear() if paused else pause_event.set()
                st.rerun()
            if st.button("Stop execution", icon=":material/stop:", width="stretch"):
                if stop_event:
                    stop_event.set()
                if pause_event:
                    pause_event.clear()
                status["message"] = "Stopping after the current browser action"
                st.rerun()

    st.subheader("Indexed documents")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        local_search = st.text_input(
            "Search captured records",
            placeholder="Instrument number, name, address, APN...",
            help="Search metadata already stored in the local SQLite database.",
        )
    with col2:
        st.metric("Records", database.count())
    with col3:
        st.metric("Carted", f"{status['cart_records']} / {status['total_records']}")
    st.download_button(
        "Download Indexed Data (CSV)", database.csv_bytes(local_search), "dona_ana_indexed_documents.csv", "text/csv"
    )
    indexed_frame = _render_table(database, local_search)
    if not indexed_frame.empty:
        with st.expander("Inspect metadata and original document", expanded=True):
            _render_record_details(database, indexed_frame)

    with st.container(border=True):
        st.subheader("Execution telemetry")
        st.write(status["message"])
        if status["logs"]:
            st.code("\n".join(status["logs"][-30:]), language="text")

    if status["running"]:
        time.sleep(1)
        st.rerun()
    elif status["error"]:
        st.error(f"{status['message']}: {status['error']}")
    else:
        st.success(status["message"] if status["message"] != "Idle" else "Ready")


if __name__ == "__main__":
    main()