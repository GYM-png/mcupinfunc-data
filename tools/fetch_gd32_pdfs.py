#!/usr/bin/env python3
"""Discover and cache GD32 datasheet PDFs without exporting CSV files."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from crawl_gd32_pdfs import (
    DEFAULT_SEED_URLS,
    CrawlFailure,
    DatasheetCandidate,
    data_repo_root,
    discover_datasheets,
    download_pdf,
    filter_candidates,
    relative_paths,
)


@dataclass(frozen=True)
class PdfFetchSuccess:
    part: str
    pdf_url: str
    source_url: str
    pdf_path: str


@dataclass
class PdfFetchReport:
    pdfs: list[PdfFetchSuccess] = field(default_factory=list)
    failures: list[CrawlFailure] = field(default_factory=list)


def fetch_candidates(candidates: Iterable[DatasheetCandidate], *, cache_dir: Path) -> PdfFetchReport:
    report = PdfFetchReport()
    for candidate in candidates:
        try:
            pdf_path = download_pdf(candidate.url, cache_dir=cache_dir)
            report.pdfs.append(
                PdfFetchSuccess(
                    part=candidate.part,
                    pdf_url=candidate.url,
                    source_url=candidate.source_url,
                    pdf_path=str(pdf_path.resolve()),
                )
            )
            print(f"OK {candidate.part}: {pdf_path}")
        except Exception as exc:
            report.failures.append(CrawlFailure(part=candidate.part, pdf_url=candidate.url, reason=str(exc)))
            print(f"FAIL {candidate.part}: {exc}", file=sys.stderr)
    return report


def write_pdf_index(path: Path, report: PdfFetchReport, root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdfs = []
    for success in report.pdfs:
        pdf_path = Path(success.pdf_path)
        pdfs.append(
            {
                **asdict(success),
                "pdf_path": relative_paths([pdf_path], root)[0],
            }
        )
    payload = {
        "summary": {
            "successes": len(report.pdfs),
            "failures": len(report.failures),
        },
        "pdfs": pdfs,
        "failures": [asdict(failure) for failure in report.failures],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and cache GD32 datasheet PDFs.")
    parser.add_argument("--seed-url", action="append", dest="seed_urls", help="Seed page URL. Can be passed more than once.")
    parser.add_argument("--repo-root", type=Path, default=data_repo_root(), help="McuPinFunc data repository root.")
    parser.add_argument("--cache-dir", type=Path, help="PDF cache directory. Defaults to <repo-root>/pdf-cache.")
    parser.add_argument("--index", type=Path, help="PDF index path. Defaults to <repo-root>/pdf-index.json.")
    parser.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl from seed URLs.")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between fetched pages, in seconds.")
    parser.add_argument("--limit", type=int, help="Maximum candidates to process after filtering.")
    parser.add_argument("--part-filter", help="Case-insensitive regex applied to inferred part numbers.")
    parser.add_argument("--dry-run", action="store_true", help="Only discover candidates and write the index without downloading.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = args.repo_root.resolve()
    cache_dir = (args.cache_dir or repo_root / "pdf-cache").resolve()
    index_path = (args.index or repo_root / "pdf-index.json").resolve()
    seed_urls = args.seed_urls or DEFAULT_SEED_URLS

    candidates = discover_datasheets(seed_urls, max_pages=args.max_pages, delay_seconds=args.delay)
    candidates = filter_candidates(candidates, args.part_filter, args.limit)
    print(f"Discovered {len(candidates)} GD32 datasheet candidate(s).")

    if args.dry_run:
        report = PdfFetchReport(
            pdfs=[
                PdfFetchSuccess(
                    part=candidate.part,
                    pdf_url=candidate.url,
                    source_url=candidate.source_url,
                    pdf_path="",
                )
                for candidate in candidates
            ]
        )
    else:
        report = fetch_candidates(candidates, cache_dir=cache_dir)

    write_pdf_index(index_path, report, repo_root)
    print(f"Index: {index_path}")
    print(f"PDF cache: {cache_dir}")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
