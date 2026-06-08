#!/usr/bin/env python3
"""Export McuPinFunc CSV files from local GD32 datasheet PDFs only."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from crawl_gd32_pdfs import (
    CrawlFailure,
    CrawlReport,
    CrawlSuccess,
    available_packages,
    data_repo_root,
    extract_gpio_af_rows,
    filter_candidates,
    gpio_af_output_name,
    infer_family_from_part,
    infer_part_from_datasheet_url,
    read_pdf_text,
    relative_paths,
    rows_to_gpio_af_csv_text,
    source_output_dir,
    write_package_csvs,
)


@dataclass(frozen=True)
class LocalDatasheet:
    part: str
    pdf_url: str
    source_url: str
    pdf_path: Path


def _resolve_index_pdf_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_pdf_index(index_path: Path, root: Path) -> list[LocalDatasheet]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    datasheets: list[LocalDatasheet] = []
    for item in payload.get("pdfs", []):
        pdf_path = _resolve_index_pdf_path(item["pdf_path"], root)
        if not item.get("part") or not pdf_path.is_file():
            continue
        datasheets.append(
            LocalDatasheet(
                part=item["part"],
                pdf_url=item.get("pdf_url", ""),
                source_url=item.get("source_url", ""),
                pdf_path=pdf_path,
            )
        )
    return datasheets


def scan_pdf_cache(cache_dir: Path) -> list[LocalDatasheet]:
    datasheets: list[LocalDatasheet] = []
    for pdf_path in sorted(cache_dir.glob("*.pdf")):
        part = infer_part_from_datasheet_url(pdf_path.as_uri())
        if not part:
            continue
        datasheets.append(LocalDatasheet(part=part, pdf_url="", source_url="cache-scan", pdf_path=pdf_path))
    return datasheets


def select_function_source(requested_source: str, part: str, pdf_path: Path) -> tuple[str, list[list[str]]]:
    if requested_source != "auto":
        return requested_source, []
    af_rows = extract_gpio_af_rows(pdf_path)
    if af_rows:
        return "gpio-af-csv", af_rows
    return "pinout-csv", []


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


def export_local_datasheets(
    datasheets: Iterable[LocalDatasheet],
    *,
    output_root: Path,
    function_source: str = "auto",
) -> CrawlReport:
    report = CrawlReport()
    for datasheet in datasheets:
        try:
            text = read_pdf_text(datasheet.pdf_path)
            packages = available_packages(text)
            if not packages:
                raise ValueError("No package definitions found")
            family = infer_family_from_part(datasheet.part)
            output_dir = source_output_dir(output_root, "gigadevice", family, datasheet.part)
            selected_function_source, af_rows = select_function_source(function_source, datasheet.part, datasheet.pdf_path)
            written = write_selected_csvs(
                datasheet.pdf_path,
                packages,
                output_dir,
                datasheet.part,
                selected_function_source,
                af_rows,
            )
            success = CrawlSuccess(
                part=datasheet.part,
                pdf_url=datasheet.pdf_url,
                packages=packages,
                function_source=selected_function_source,
                written_files=relative_paths(written, output_root),
            )
            report.successes.append(success)
            print(f"OK {success.part}: {', '.join(success.packages)}")
        except Exception as exc:
            report.failures.append(CrawlFailure(part=datasheet.part, pdf_url=datasheet.pdf_url, reason=str(exc)))
            print(f"FAIL {datasheet.part}: {exc}", file=sys.stderr)
    return report


def filter_local_datasheets(
    datasheets: Iterable[LocalDatasheet],
    part_filter: str | None,
    limit: int | None,
) -> list[LocalDatasheet]:
    pattern = re.compile(part_filter, re.I) if part_filter else None
    filtered = [datasheet for datasheet in datasheets if not pattern or pattern.search(datasheet.part)]
    return filtered[:limit] if limit is not None else filtered


def write_report(path: Path, report: CrawlReport) -> None:
    from crawl_gd32_pdfs import write_report as write_crawl_report

    write_crawl_report(path, report)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export McuPinFunc CSVs from local GD32 datasheet PDFs.")
    parser.add_argument("--repo-root", type=Path, default=data_repo_root(), help="McuPinFunc data repository root.")
    parser.add_argument("--pdf-index", type=Path, help="PDF index path. Defaults to <repo-root>/pdf-index.json when it exists.")
    parser.add_argument("--cache-dir", type=Path, help="PDF cache directory. Defaults to <repo-root>/pdf-cache.")
    parser.add_argument("--scan-cache", action="store_true", help="Ignore pdf-index and scan cache-dir for PDFs.")
    parser.add_argument("--output-root", type=Path, help="Output root. Defaults to staging/gd32-csv-export under --repo-root.")
    parser.add_argument("--report", type=Path, help="Report JSON path. Defaults to <output-root>/export-report.json.")
    parser.add_argument("--limit", type=int, help="Maximum local PDFs to process after filtering.")
    parser.add_argument("--part-filter", help="Case-insensitive regex applied to part numbers.")
    parser.add_argument(
        "--function-source",
        choices=["auto", "gpio-af-csv", "pinout-csv"],
        default="auto",
        help="Function extraction mode. auto uses GPIO AF tables when present and pinout functions otherwise.",
    )
    parser.add_argument(
        "--write-to-repo",
        action="store_true",
        help="Write CSVs directly into the data repository instead of staging/gd32-csv-export.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    repo_root = args.repo_root.resolve()
    output_root = repo_root if args.write_to_repo else (args.output_root or repo_root / "staging" / "gd32-csv-export").resolve()
    cache_dir = (args.cache_dir or repo_root / "pdf-cache").resolve()
    index_path = (args.pdf_index or repo_root / "pdf-index.json").resolve()
    report_path = (args.report or output_root / "export-report.json").resolve()

    if not args.scan_cache and index_path.is_file():
        datasheets = load_pdf_index(index_path, repo_root)
        source = str(index_path)
    else:
        datasheets = scan_pdf_cache(cache_dir)
        source = str(cache_dir)
    datasheets = filter_local_datasheets(datasheets, args.part_filter, args.limit)
    print(f"Loaded {len(datasheets)} local GD32 datasheet PDF(s) from {source}.")

    report = export_local_datasheets(datasheets, output_root=output_root, function_source=args.function_source)
    write_report(report_path, report)
    print(f"Report: {report_path}")
    print(f"Output root: {output_root}")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
