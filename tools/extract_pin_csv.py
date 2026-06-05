#!/usr/bin/env python3
"""Extract McuPinFunc CSV files from text datasheet PDFs.

Examples:
  python tools/extract_pin_csv.py --pdf "GD32F407xx_Datasheet.pdf" --packages LQFP144,LQFP100
  python tools/extract_pin_csv.py --pdf-url "https://example.com/GD32H759xx_Datasheet.pdf" --part GD32H759 --packages LQFP176

By default this script writes into the data repository layout:
  chips/<vendor>/<family>/<part>/source/<PART>_GPIO_AF.csv
  chips/<vendor>/<family>/<part>/source/<PART>_<PACKAGE>_PINOUT.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PinRow:
    pad_number: int | str
    pin_name: str
    pin_type: str
    alternate: str = ""
    remap: str = ""


ROW_RE = re.compile(
    r"^(?:(?P<name>.*?)\s+)?(?P<pin>\d{1,3}|[A-Z]{1,2}[1-9]\d?)\s+"
    r"(?P<table_type>I/O|I|O|P|-)(?:\s+(?P<level>5VT|-))?(?:\s|$)"
)
SECTION_HEADER_RE = re.compile(r"\b(?P<package>(?:[A-Z]+FP|BGA)\d+)\s+pin definitions\b", re.I)
PART_RE = re.compile(r"(GD32[A-Z0-9]+?)(?:xx|x)?(?:[\s_\-]*Datasheet|$)", re.I)
PIN_NAME_RE = re.compile(r"^P[A-Z]\d{1,2}$")
PACKAGE_PIN_NAME_RE = re.compile(r"^(?:P[A-Z]\d{1,2}(?:[-/].*)?|V[A-Z0-9_+]+|NC|NRST|BOOT0|PDR_ON)$", re.I)
GPIO_AF_HEADER = ["PinName", *[f"AF{i}" for i in range(16)]]

IGNORED_PREFIXES = (
    "Table ",
    "Pin Name",
    "Pin ",
    "Type",
    "I/O",
    "Level",
    "Functions description",
    "Default:",
    "Alternate:",
    "Additional:",
    "Notes:",
    "(",
)
FUNCTION_LABEL_RE = re.compile(r"^(Default|Alternate|Remap):\s*(.*)$", re.I)
FOOTNOTE_RE = re.compile(r"\(\d+\)")


def dependency_help_message(package: str = "pypdf") -> str:
    bundled_python = (
        r"C:\Users\GYM\.cache\codex-runtimes\codex-primary-runtime"
        r"\dependencies\python\python.exe"
    )
    return (
        f"Missing Python dependency: {package}\n"
        f"Install it for your current Python: python -m pip install {package}\n"
        f"Or run this script with the bundled Codex Python:\n"
        f'  "{bundled_python}" tools/extract_pin_csv.py --pdf-url "PDF_URL" --packages LQFP144,LQFP100'
    )


def data_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_slug(value: str, label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"{label} must contain at least one safe path character.")
    return slug


def normalize_part(part: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", part.strip()).upper()
    if not normalized:
        raise ValueError("part must contain at least one alphanumeric character.")
    return normalized


def normalize_package(package: str) -> str:
    return str(package).strip().upper().replace("-", "").replace(" ", "")


def infer_part_name(pdf_path_or_name: str | Path) -> str:
    """Infer output prefix, e.g. GD32H759 from GD32H759xx Datasheet_Rev2.2.pdf."""
    name = Path(str(pdf_path_or_name)).name
    stem = Path(name).stem
    series_match = re.search(r"\b(GD32[A-Z]\d{3})", stem, re.I)
    if series_match:
        return normalize_part(series_match.group(1))
    match = PART_RE.search(stem)
    if match:
        return normalize_part(match.group(1))
    cleaned = re.sub(r"(?i)[\s_\-]*Datasheet.*$", "", stem)
    cleaned = re.sub(r"(?i)[\s_\-]*Rev[\d.]+.*$", "", cleaned)
    cleaned = re.sub(r"(?i)xx$", "", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned).strip("_") or "PINOUT"
    return normalize_part(cleaned)


def infer_family_from_part(part: str) -> str:
    normalized = normalize_part(part)
    match = re.match(r"^GD32([A-Z])(\d)", normalized, re.I)
    if not match:
        raise ValueError(f"Cannot infer family from part {part}. Pass --family explicitly.")
    return f"gd32{match.group(1).lower()}{match.group(2)}"


def source_output_dir(repo_root: Path, vendor: str, family: str, part: str) -> Path:
    return repo_root / "chips" / normalize_slug(vendor, "vendor") / normalize_slug(family, "family") / normalize_part(part).lower() / "source"


def available_packages(text: str) -> list[str]:
    seen: set[str] = set()
    packages: list[str] = []
    for match in SECTION_HEADER_RE.finditer(text):
        package = normalize_package(match.group("package"))
        if package not in seen:
            seen.add(package)
            packages.append(package)
    return packages


def classify_pin(pin_name: str, table_type: str) -> str:
    name = pin_name.upper()
    power_names = {
        "VBAT",
        "VDD",
        "VDDA",
        "VREF+",
        "VREFP",
        "VCAP_1",
        "VCAP_2",
        "PDR_ON",
        "VCORE",
        "VDDLDO",
    }
    if name == "NC":
        return "nc"
    if name in {"VSS", "VSSA"} or name.startswith("VSS"):
        return "ground"
    if name == "NRST":
        return "reset"
    if table_type == "P" or name in power_names:
        return "power"
    if table_type == "I/O":
        return "gpio"
    if table_type == "I":
        return "input"
    if table_type == "O":
        return "output"
    return "other"


def read_pdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise RuntimeError(dependency_help_message("pypdf")) from exc

    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError(f"{pdf_path} has no extractable text layer. Use an original text PDF or OCR it first.")
    return text


def download_pdf(url: str, cache_dir: Path | None = None) -> Path:
    cache_dir = cache_dir or Path(tempfile.gettempdir()) / "pin_csv_pdf_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    filename = Path(url_path).name or "datasheet.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    out_path = cache_dir / filename
    urllib.request.urlretrieve(url, out_path)
    return out_path


def _clean_line(line: str) -> str:
    return " ".join(line.strip().split())


def _clean_function_item(value: str) -> str:
    return FOOTNOTE_RE.sub("", value).strip()


def _function_cell(parts: list[str]) -> str:
    items: list[str] = []
    for part in parts:
        for item in part.split(","):
            cleaned = _clean_function_item(item)
            if cleaned:
                items.append(cleaned)
    return "/".join(dict.fromkeys(items))


def _append_function_part(parts: list[str], value: str) -> None:
    value = value.strip().rstrip(".;")
    if value:
        parts.append(value)


def _looks_like_package_pin_name(pin_name: str) -> bool:
    return bool(PACKAGE_PIN_NAME_RE.fullmatch(pin_name.strip()))


def _valid_package_row_match(match: re.Match[str]) -> bool:
    inline_name = (match.group("name") or "").strip()
    return not inline_name or _looks_like_package_pin_name(inline_name)


def _candidate_has_package_rows(candidate: str) -> bool:
    for line in candidate.splitlines():
        row_match = ROW_RE.match(_clean_line(line))
        if row_match and _valid_package_row_match(row_match):
            return True
    return False


def find_section(text: str, package: str) -> str:
    package = normalize_package(package)
    matches = list(SECTION_HEADER_RE.finditer(text))
    chosen = None
    for i, match in enumerate(matches):
        if normalize_package(match.group("package")) != package:
            continue
        next_different = None
        for later in matches[i + 1 :]:
            if normalize_package(later.group("package")) != package:
                next_different = later
                break
        if next_different:
            end_index = next_different.start()
        else:
            remainder = text[match.end() :]
            next_section = re.search(r"\n\s*[23]\.\d+(?:\.\d+)?\.", remainder)
            end_index = match.end() + next_section.start() if next_section else len(text)
        candidate = text[match.start() : end_index]
        if _candidate_has_package_rows(candidate):
            chosen = (match, end_index)
            break
    if not chosen:
        found = ", ".join(available_packages(text)) or "none"
        raise ValueError(f"Could not find {package} pin definitions. Available packages in this PDF: {found}")
    start, end_index = chosen
    return text[start.start() : end_index]


def _is_candidate_name_fragment(line: str) -> bool:
    if not line or line.startswith(IGNORED_PREFIXES):
        return False
    if "Datasheet" in line or line.isdigit():
        return False
    if line in {"Pin", "Type", "I/O", "Level", "Pins"}:
        return False
    if SECTION_HEADER_RE.search(line):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_+/\-]+", line))


def _join_pin_name(parts: Iterable[str]) -> str:
    name = "".join(parts).replace("--", "-")
    return name.rstrip("-") if name.endswith("--") else name


def is_bga_package(package: str) -> bool:
    return normalize_package(package).startswith("BGA")


def _position_sort_key(position: int | str) -> tuple[int, str, int]:
    value = str(position)
    if value.isdigit():
        return (0, "", int(value))
    match = re.fullmatch(r"([A-Z]+)(\d+)", value.upper())
    if match:
        return (1, match.group(1), int(match.group(2)))
    return (2, value.upper(), 0)


def extract_package_rows(text: str, package: str, include_functions: bool = False) -> list[PinRow]:
    section = find_section(text, package)
    pending_name_parts: list[str] = []
    raw_rows: list[tuple[int | str, str, str, list[str], list[str]]] = []
    current_alternate_parts: list[str] = []
    current_remap_parts: list[str] = []
    current_function_target: str | None = None
    active_row_index: int | None = None

    for raw_line in section.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue

        if include_functions:
            function_label = FUNCTION_LABEL_RE.match(line)
            if function_label:
                label = function_label.group(1).lower()
                value = function_label.group(2)
                if label == "default":
                    current_alternate_parts = []
                    current_remap_parts = []
                    current_function_target = None
                    active_row_index = None
                    pending_name_parts.clear()
                    continue
                current_function_target = "alternate" if label == "alternate" else "remap"
                if active_row_index is not None:
                    target_parts = raw_rows[active_row_index][3 if current_function_target == "alternate" else 4]
                else:
                    target_parts = current_alternate_parts if current_function_target == "alternate" else current_remap_parts
                _append_function_part(target_parts, value)
                pending_name_parts.clear()
                continue

        match = ROW_RE.match(line)
        if match:
            raw_position = match.group("pin")
            pad_number: int | str = int(raw_position) if raw_position.isdigit() else raw_position.upper()
            table_type = match.group("table_type")
            inline_name = (match.group("name") or "").strip()
            if inline_name and not _looks_like_package_pin_name(inline_name):
                continue
            if pending_name_parts and not inline_name:
                pin_name = _join_pin_name(pending_name_parts)
            else:
                pin_name = inline_name
            if pin_name and not _looks_like_package_pin_name(pin_name):
                continue
            pending_name_parts.clear()
            raw_rows.append((pad_number, pin_name, table_type, current_alternate_parts.copy(), current_remap_parts.copy()))
            if include_functions:
                active_row_index = len(raw_rows) - 1
                current_alternate_parts = []
                current_remap_parts = []
            continue

        if include_functions and current_function_target in {"alternate", "remap"}:
            if active_row_index is not None:
                target_parts = raw_rows[active_row_index][3 if current_function_target == "alternate" else 4]
            else:
                target_parts = current_alternate_parts if current_function_target == "alternate" else current_remap_parts
            _append_function_part(target_parts, line)
            pending_name_parts.clear()
            continue

        if _is_candidate_name_fragment(line):
            if raw_rows and raw_rows[-1][1].endswith("-") and not pending_name_parts:
                pad, old_name, old_type, alternate_parts, remap_parts = raw_rows[-1]
                raw_rows[-1] = (pad, _join_pin_name([old_name, line]), old_type, alternate_parts, remap_parts)
            else:
                pending_name_parts.append(line)
        else:
            pending_name_parts.clear()
            if include_functions:
                current_function_target = None
                active_row_index = None

    deduped: dict[int | str, tuple[str, str, list[str], list[str]]] = {}
    for pad_number, pin_name, table_type, alternate_parts, remap_parts in raw_rows:
        if pin_name and pad_number not in deduped:
            deduped[pad_number] = (pin_name, table_type, alternate_parts, remap_parts)

    return [
        PinRow(pad_number, pin_name, classify_pin(pin_name, table_type), _function_cell(alternate_parts), _function_cell(remap_parts))
        for pad_number, (pin_name, table_type, alternate_parts, remap_parts) in sorted(
            deduped.items(), key=lambda item: _position_sort_key(item[0])
        )
    ]


def rows_to_csv_text(rows: Iterable[PinRow], package: str = "", include_functions: bool = False) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    first_header = "BallName" if is_bga_package(package) else "PadNumber"
    header = [first_header, "PinName", "PinType"]
    if include_functions:
        header.extend(["Alternate", "Remap"])
    writer.writerow(header)
    for row in rows:
        values = [row.pad_number, row.pin_name, row.pin_type]
        if include_functions:
            values.extend([row.alternate, row.remap])
        writer.writerow(values)
    return output.getvalue()


def clean_af_cell(value: str | None) -> str:
    """Normalize wrapped pdfplumber table-cell text such as EVENTOU\\nT."""
    if not value:
        return ""
    return re.sub(r"\s+", "", value)


def rows_to_gpio_af_csv_text(rows: Iterable[list[str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(GPIO_AF_HEADER)
    for row in rows:
        padded = (row + [""] * len(GPIO_AF_HEADER))[: len(GPIO_AF_HEADER)]
        writer.writerow(padded)
    return output.getvalue()


def extract_gpio_af_rows(pdf_path: Path) -> list[list[str]]:
    """Extract GPIO alternate-function summary rows using pdfplumber tables."""
    try:
        import pdfplumber
    except ModuleNotFoundError as exc:
        raise RuntimeError(dependency_help_message("pdfplumber")) from exc

    rows: list[list[str]] = []
    seen: set[str] = set()
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or max((len(row) for row in table if row), default=0) < 17:
                    continue
                for raw_row in table:
                    if not raw_row:
                        continue
                    pin_name = clean_af_cell(raw_row[0])
                    if not PIN_NAME_RE.fullmatch(pin_name):
                        continue
                    values = [pin_name, *[clean_af_cell(cell) for cell in raw_row[1:17]]]
                    if pin_name not in seen:
                        rows.append(values)
                        seen.add(pin_name)
    return rows


def package_output_name(part: str, package: str) -> str:
    return f"{normalize_part(part)}_{normalize_package(package)}_PINOUT.csv"


def gpio_af_output_name(part: str) -> str:
    return f"{normalize_part(part)}_GPIO_AF.csv"


def write_package_csvs(
    pdf_path: Path,
    packages: Iterable[str],
    output_dir: Path,
    part: str,
    write_gpio_af: bool = True,
    include_functions: bool = False,
) -> list[Path]:
    text = read_pdf_text(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for package in packages:
        package = normalize_package(package)
        rows = extract_package_rows(text, package, include_functions=include_functions)
        if not rows:
            raise ValueError(f"No pin rows extracted for {package}.")
        out_path = output_dir / package_output_name(part, package)
        out_path.write_text(rows_to_csv_text(rows, package, include_functions=include_functions), encoding="utf-8", newline="")
        written.append(out_path)

    if write_gpio_af:
        af_rows = extract_gpio_af_rows(pdf_path)
        if af_rows:
            out_path = output_dir / gpio_af_output_name(part)
            out_path.write_text(rows_to_gpio_af_csv_text(af_rows), encoding="utf-8", newline="")
            written.append(out_path)

    return written


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract McuPinFunc CSVs from a text PDF into the data repo layout.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path, help="Local PDF path")
    source.add_argument("--pdf-url", help="PDF download URL")
    parser.add_argument("--vendor", default="gigadevice", help="Vendor slug. Defaults to gigadevice.")
    parser.add_argument("--family", help="Family slug, e.g. gd32f4. Defaults to inference from --part or PDF name.")
    parser.add_argument("--part", help="Part number, e.g. GD32F407. Defaults to PDF filename inference.")
    parser.add_argument("--packages", required=True, help="Comma-separated packages, e.g. LQFP144,LQFP100")
    parser.add_argument("--repo-root", type=Path, default=data_repo_root(), help="McuPinFunc data repository root")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override CSV output directory. Defaults to chips/<vendor>/<family>/<part>/source under --repo-root.",
    )
    parser.add_argument(
        "--no-gpio-af",
        action="store_true",
        help="Do not write the extra GPIO alternate-function CSV",
    )
    parser.add_argument(
        "--pinout-functions",
        action="store_true",
        help="Write Alternate and Remap columns into package pinout CSVs when present in pin definition tables.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    pdf_path = args.pdf if args.pdf else download_pdf(args.pdf_url)
    part = normalize_part(args.part) if args.part else infer_part_name(pdf_path)
    family = args.family or infer_family_from_part(part)
    output_dir = args.output_dir or source_output_dir(args.repo_root.resolve(), args.vendor, family, part)
    packages = [p.strip() for p in args.packages.split(",") if p.strip()]

    try:
        written = write_package_csvs(
            pdf_path,
            packages,
            output_dir,
            part,
            write_gpio_af=not args.no_gpio_af,
            include_functions=args.pinout_functions,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Part: {part}")
    print(f"Output directory: {output_dir.resolve()}")
    for path in written:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
