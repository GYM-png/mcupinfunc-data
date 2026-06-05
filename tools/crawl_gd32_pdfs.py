#!/usr/bin/env python3
"""Discover GD32 datasheets and batch-extract McuPinFunc CSVs.

This script is intentionally separate from extract_pin_csv.py. It uses that
module as the single source of truth for PDF parsing and CSV writing.

Examples:
  python tools/crawl_gd32_pdfs.py --dry-run --limit 20
  python tools/crawl_gd32_pdfs.py --part-filter "^GD32F4" --limit 5
  python tools/crawl_gd32_pdfs.py --write-to-repo --part-filter "^GD32F407$"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from extract_pin_csv import (
    available_packages,
    data_repo_root,
    download_pdf,
    extract_gpio_af_rows,
    gpio_af_output_name,
    infer_family_from_part,
    normalize_part,
    read_pdf_text,
    rows_to_gpio_af_csv_text,
    source_output_dir,
    write_package_csvs,
)


DEFAULT_SEED_URLS = [
    "https://www.gigadevice.com/products/microcontrollers/gd32/",
]

USER_AGENT = "McuPinFunc-data-crawler/0.1 (+https://github.com/GYM-png/mcupinfunc-data)"
FetchText = Callable[[str], str]


@dataclass(frozen=True)
class DatasheetCandidate:
    part: str
    url: str
    source_url: str


@dataclass(frozen=True)
class CrawlSuccess:
    part: str
    pdf_url: str
    packages: list[str]
    function_source: str
    written_files: list[str]


@dataclass(frozen=True)
class CrawlFailure:
    part: str
    pdf_url: str
    reason: str


@dataclass
class CrawlReport:
    successes: list[CrawlSuccess] = field(default_factory=list)
    failures: list[CrawlFailure] = field(default_factory=list)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, "ignore")


def normalize_url(base_url: str, href: str) -> str:
    joined = urllib.parse.urljoin(base_url, href.strip())
    parsed = urllib.parse.urlsplit(joined)
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            urllib.parse.quote(urllib.parse.unquote(parsed.path), safe="/:"),
            urllib.parse.quote(urllib.parse.unquote(parsed.query), safe="=&?/:"),
            urllib.parse.quote(urllib.parse.unquote(parsed.fragment), safe="=&?/:"),
        )
    )


def html_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html, re.I):
        url = normalize_url(base_url, match.group(1))
        if url not in seen:
            links.append(url)
            seen.add(url)
    return links


def is_gd32_product_page(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower().rstrip("/")
    return "/product/mcu/" in path and "gd32" in path


def is_gd32_datasheet_pdf(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    filename = urllib.parse.unquote(Path(parsed.path).name)
    normalized = filename.lower()
    return (
        filename.lower().endswith(".pdf")
        and "gd32" in normalized
        and "datasheet" in normalized
        and "user_manual" not in normalized
        and "application_note" not in normalized
    )


def infer_part_from_datasheet_url(url: str) -> str | None:
    filename = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    match = re.search(r"\b(GD32[A-Z]\d{3}[A-Z0-9]*)", filename, re.I)
    if not match:
        return None
    return normalize_part(re.sub(r"xx$", "", match.group(1), flags=re.I))


def extract_product_links(html: str, base_url: str) -> list[str]:
    return [url for url in html_links(html, base_url) if is_gd32_product_page(url)]


def extract_datasheet_candidates(html: str, source_url: str) -> list[DatasheetCandidate]:
    candidates: list[DatasheetCandidate] = []
    seen_parts: set[str] = set()
    for url in html_links(html, source_url):
        if not is_gd32_datasheet_pdf(url):
            continue
        part = infer_part_from_datasheet_url(url)
        if not part or part in seen_parts:
            continue
        candidates.append(DatasheetCandidate(part=part, url=url, source_url=source_url))
        seen_parts.add(part)
    return candidates


def discover_datasheets(
    seed_urls: Iterable[str],
    *,
    max_pages: int,
    delay_seconds: float,
    fetcher: FetchText = fetch_text,
) -> list[DatasheetCandidate]:
    queue = list(dict.fromkeys(seed_urls))
    visited: set[str] = set()
    candidates_by_part: dict[str, DatasheetCandidate] = {}

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            html = fetcher(url)
        except Exception as exc:
            print(f"Skipping {url}: {exc}", file=sys.stderr)
            continue

        for candidate in extract_datasheet_candidates(html, url):
            candidates_by_part.setdefault(candidate.part, candidate)

        for link in extract_product_links(html, url):
            if link not in visited and link not in queue:
                queue.append(link)

        if delay_seconds > 0 and queue:
            time.sleep(delay_seconds)

    return sorted(candidates_by_part.values(), key=lambda candidate: candidate.part)


def filter_candidates(
    candidates: Iterable[DatasheetCandidate],
    part_filter: str | None,
    limit: int | None,
) -> list[DatasheetCandidate]:
    pattern = re.compile(part_filter, re.I) if part_filter else None
    filtered = [candidate for candidate in candidates if not pattern or pattern.search(candidate.part)]
    return filtered[:limit] if limit is not None else filtered


def relative_paths(paths: Iterable[Path], root: Path) -> list[str]:
    root = root.resolve()
    result: list[str] = []
    for path in paths:
        try:
            result.append(path.resolve().relative_to(root).as_posix())
        except ValueError:
            result.append(str(path.resolve()))
    return result


def infer_function_source(part: str, pdf_path: Path) -> tuple[str, list[list[str]]]:
    af_rows = extract_gpio_af_rows(pdf_path)
    if af_rows:
        return "gpio-af-csv", af_rows
    return "pinout-csv", []


def select_function_source(requested_source: str, part: str, pdf_path: Path) -> tuple[str, list[list[str]]]:
    if requested_source != "auto":
        return requested_source, []
    return infer_function_source(part, pdf_path)


def write_selected_csvs(
    pdf_path: Path,
    packages: list[str],
    output_dir: Path,
    part: str,
    function_source: str,
    af_rows: list[list[str]],
) -> list[Path]:
    if function_source == "gpio-af-csv" and af_rows:
        written = write_package_csvs(
            pdf_path,
            packages,
            output_dir,
            part,
            write_gpio_af=False,
            include_functions=False,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        af_path = output_dir / gpio_af_output_name(part)
        af_path.write_text(rows_to_gpio_af_csv_text(af_rows), encoding="utf-8", newline="")
        written.append(af_path)
        return written

    return write_package_csvs(
        pdf_path,
        packages,
        output_dir,
        part,
        write_gpio_af=function_source == "gpio-af-csv",
        include_functions=function_source == "pinout-csv",
    )


def extract_candidate(
    candidate: DatasheetCandidate,
    output_root: Path,
    cache_dir: Path,
    function_source: str = "auto",
) -> CrawlSuccess:
    pdf_path = download_pdf(candidate.url, cache_dir=cache_dir)
    text = read_pdf_text(pdf_path)
    packages = available_packages(text)
    if not packages:
        raise ValueError("No package definitions found")

    family = infer_family_from_part(candidate.part)
    output_dir = source_output_dir(output_root, "gigadevice", family, candidate.part)
    selected_function_source, af_rows = select_function_source(function_source, candidate.part, pdf_path)
    written = write_selected_csvs(
        pdf_path,
        packages,
        output_dir,
        candidate.part,
        selected_function_source,
        af_rows,
    )
    return CrawlSuccess(
        part=candidate.part,
        pdf_url=candidate.url,
        packages=packages,
        function_source=selected_function_source,
        written_files=relative_paths(written, output_root),
    )


def crawl_and_extract(
    candidates: Iterable[DatasheetCandidate],
    *,
    output_root: Path,
    cache_dir: Path,
    function_source: str = "auto",
) -> CrawlReport:
    report = CrawlReport()
    for candidate in candidates:
        try:
            success = extract_candidate(candidate, output_root, cache_dir, function_source)
            report.successes.append(success)
            print(f"OK {success.part}: {', '.join(success.packages)}")
        except Exception as exc:
            report.failures.append(CrawlFailure(part=candidate.part, pdf_url=candidate.url, reason=str(exc)))
            print(f"FAIL {candidate.part}: {exc}", file=sys.stderr)
    return report


def write_report(path: Path, report: CrawlReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "successes": len(report.successes),
            "failures": len(report.failures),
        },
        "successes": [asdict(success) for success in report.successes],
        "failures": [asdict(failure) for failure in report.failures],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl GD32 datasheets and batch-extract McuPinFunc CSVs.")
    parser.add_argument("--seed-url", action="append", dest="seed_urls", help="Seed page URL. Can be passed more than once.")
    parser.add_argument("--repo-root", type=Path, default=data_repo_root(), help="McuPinFunc data repository root.")
    parser.add_argument("--output-root", type=Path, help="Output root. Defaults to staging/gd32-crawl under --repo-root.")
    parser.add_argument("--cache-dir", type=Path, help="PDF cache directory. Defaults to <output-root>/pdf-cache.")
    parser.add_argument("--report", type=Path, help="Report JSON path. Defaults to <output-root>/crawl-report.json.")
    parser.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl from seed URLs.")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between fetched pages, in seconds.")
    parser.add_argument("--limit", type=int, help="Maximum candidates to process after filtering.")
    parser.add_argument("--part-filter", help="Case-insensitive regex applied to inferred part numbers.")
    parser.add_argument("--dry-run", action="store_true", help="Only discover candidates and write the report.")
    parser.add_argument(
        "--function-source",
        choices=["auto", "gpio-af-csv", "pinout-csv"],
        default="auto",
        help="Function extraction mode. auto uses GPIO AF tables when present and pinout functions otherwise.",
    )
    parser.add_argument(
        "--write-to-repo",
        action="store_true",
        help="Write CSVs directly into the data repository instead of staging/gd32-crawl.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = args.repo_root.resolve()
    output_root = repo_root if args.write_to_repo else (args.output_root or repo_root / "staging" / "gd32-crawl").resolve()
    cache_dir = (args.cache_dir or output_root / "pdf-cache").resolve()
    report_path = (args.report or output_root / "crawl-report.json").resolve()
    seed_urls = args.seed_urls or DEFAULT_SEED_URLS

    candidates = discover_datasheets(seed_urls, max_pages=args.max_pages, delay_seconds=args.delay)
    candidates = filter_candidates(candidates, args.part_filter, args.limit)
    print(f"Discovered {len(candidates)} GD32 datasheet candidate(s).")

    if args.dry_run:
        report = CrawlReport(
            successes=[
                CrawlSuccess(
                    part=candidate.part,
                    pdf_url=candidate.url,
                    packages=[],
                    function_source=args.function_source,
                    written_files=[],
                )
                for candidate in candidates
            ],
        )
    else:
        report = crawl_and_extract(
            candidates,
            output_root=output_root,
            cache_dir=cache_dir,
            function_source=args.function_source,
        )

    write_report(report_path, report)
    print(f"Report: {report_path}")
    print(f"Output root: {output_root}")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
