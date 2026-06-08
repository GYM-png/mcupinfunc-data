import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import crawl_gd32_pdfs as crawler
import export_gd32_csvs as local_exporter
import fetch_gd32_pdfs as pdf_fetcher


class CrawlGd32PdfsTest(unittest.TestCase):
    def test_extracts_unique_gd32_datasheet_candidates_from_html(self) -> None:
        html = """
        <a href="https://download.gigadevice.com/Datasheet/GD32F407xx_Datasheet_Rev3.0.pdf">datasheet</a>
        <a href="https://download.gigadevice.com/Datasheet/GD32F407xx_Datasheet_Rev3.0.pdf">duplicate</a>
        <a href="https://download.gigadevice.com/User_Manual/GD32F4xx_User_Manual_Rev3.3.pdf">manual</a>
        <a href="/Datasheet/GD32H759xx_Datasheet_Rev2.2.pdf">relative</a>
        """

        candidates = crawler.extract_datasheet_candidates(
            html,
            "https://www.gigadevice.com/product/mcu/high-performance-mcus/gd32f4xx-series/gd32f407",
        )

        self.assertEqual([candidate.part for candidate in candidates], ["GD32F407", "GD32H759"])
        self.assertEqual(
            candidates[1].url,
            "https://www.gigadevice.com/Datasheet/GD32H759xx_Datasheet_Rev2.2.pdf",
        )

    def test_percent_encodes_spaces_in_discovered_pdf_urls(self) -> None:
        html = """
        <a href="https://download.gigadevice.com/Datasheet/GD32F103xx Datasheet_Rev3.3.pdf">datasheet</a>
        """

        candidates = crawler.extract_datasheet_candidates(html, "https://www.gigadevice.com/products/microcontrollers/gd32/")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].url,
            "https://download.gigadevice.com/Datasheet/GD32F103xx%20Datasheet_Rev3.3.pdf",
        )

    def test_discovers_product_links_under_mcu_gd32_pages(self) -> None:
        html = """
        <a href="/product/mcu/high-performance-mcus/gd32f4xx-series/gd32f407">GD32F407</a>
        <a href="https://www.gigadevice.com/product/mcu/wireless-mcus/gd32w515">GD32W515</a>
        <a href="/about/news-and-event/news/gd32f5-gd32g5-iec61508">news</a>
        <a href="/product/memory/nor-flash">flash</a>
        """

        links = crawler.extract_product_links(html, "https://www.gigadevice.com/products/microcontrollers/gd32/")

        self.assertEqual(
            links,
            [
                "https://www.gigadevice.com/product/mcu/high-performance-mcus/gd32f4xx-series/gd32f407",
                "https://www.gigadevice.com/product/mcu/wireless-mcus/gd32w515",
            ],
        )

    def test_report_writes_successes_and_failures_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "crawl-report.json"
            report = crawler.CrawlReport(
                successes=[
                    crawler.CrawlSuccess(
                        part="GD32F407",
                        pdf_url="https://download.gigadevice.com/Datasheet/GD32F407xx_Datasheet_Rev3.0.pdf",
                        packages=["LQFP100", "LQFP144"],
                        function_source="gpio-af-csv",
                        written_files=["chips/gigadevice/gd32f4/gd32f407/source/GD32F407_GPIO_AF.csv"],
                    )
                ],
                failures=[
                    crawler.CrawlFailure(
                        part="GD32X000",
                        pdf_url="https://download.gigadevice.com/Datasheet/GD32X000xx_Datasheet.pdf",
                        reason="No package definitions found",
                    )
                ],
            )

            crawler.write_report(report_path, report)

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"], {"successes": 1, "failures": 1})
            self.assertEqual(payload["successes"][0]["part"], "GD32F407")
            self.assertEqual(payload["failures"][0]["reason"], "No package definitions found")

    def test_report_includes_function_source_for_successes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "crawl-report.json"
            report = crawler.CrawlReport(
                successes=[
                    crawler.CrawlSuccess(
                        part="GD32F103",
                        pdf_url="https://download.gigadevice.com/Datasheet/GD32F103xx%20Datasheet_Rev3.3.pdf",
                        packages=["LQFP100"],
                        function_source="pinout-csv",
                        written_files=["chips/gigadevice/gd32f1/gd32f103/source/GD32F103_LQFP100_PINOUT.csv"],
                    )
                ]
            )

            crawler.write_report(report_path, report)

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["successes"][0]["function_source"], "pinout-csv")

    def test_fetch_candidates_writes_relative_pdf_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "pdf-cache"
            cached_pdf = cache_dir / "GD32F103xx Datasheet_Rev3.3.pdf"
            cached_pdf.parent.mkdir(parents=True)
            cached_pdf.write_bytes(b"%PDF cached")
            candidate = crawler.DatasheetCandidate(
                part="GD32F103",
                url="https://download.gigadevice.com/Datasheet/GD32F103xx%20Datasheet_Rev3.3.pdf",
                source_url="https://www.gigadevice.com/product/mcu/gd32f103",
            )

            with patch.object(pdf_fetcher, "download_pdf", return_value=cached_pdf):
                report = pdf_fetcher.fetch_candidates([candidate], cache_dir=cache_dir)
            index_path = root / "pdf-index.json"
            pdf_fetcher.write_pdf_index(index_path, report, root)

            payload = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"], {"successes": 1, "failures": 0})
            self.assertEqual(payload["pdfs"][0]["part"], "GD32F103")
            self.assertEqual(payload["pdfs"][0]["pdf_path"], "pdf-cache/GD32F103xx Datasheet_Rev3.3.pdf")

    def test_export_local_datasheets_uses_local_pdf_index_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "pdf-cache" / "GD32F103xx Datasheet_Rev3.3.pdf"
            pdf_path.parent.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF cached")
            index_path = root / "pdf-index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "summary": {"successes": 1, "failures": 0},
                        "pdfs": [
                            {
                                "part": "GD32F103",
                                "pdf_url": "https://download.gigadevice.com/Datasheet/GD32F103xx%20Datasheet_Rev3.3.pdf",
                                "source_url": "https://www.gigadevice.com/product/mcu/gd32f103",
                                "pdf_path": "pdf-cache/GD32F103xx Datasheet_Rev3.3.pdf",
                            }
                        ],
                        "failures": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            written_path = root / "chips/gigadevice/gd32f1/gd32f103/source/GD32F103_LQFP100_PINOUT.csv"

            datasheets = local_exporter.load_pdf_index(index_path, root)
            with (
                patch.object(local_exporter, "read_pdf_text", return_value="Table 2-6. LQFP100 pin definitions"),
                patch.object(local_exporter, "available_packages", return_value=["LQFP100"]),
                patch.object(local_exporter, "extract_gpio_af_rows", return_value=[]),
                patch.object(local_exporter, "write_package_csvs", return_value=[written_path]) as write_package_csvs,
            ):
                report = local_exporter.export_local_datasheets(
                    datasheets,
                    output_root=root,
                    function_source="auto",
                )

            self.assertEqual(len(report.successes), 1)
            self.assertEqual(report.successes[0].part, "GD32F103")
            self.assertEqual(report.successes[0].function_source, "pinout-csv")
            write_package_csvs.assert_called_once_with(
                pdf_path,
                ["LQFP100"],
                root / "chips/gigadevice/gd32f1/gd32f103/source",
                "GD32F103",
                write_gpio_af=False,
                include_functions=True,
            )

    def test_parse_args_accepts_function_source_override(self) -> None:
        args = crawler.parse_args(["--function-source", "pinout-csv"])

        self.assertEqual(args.function_source, "pinout-csv")

    def test_extract_candidate_writes_pinout_functions_when_auto_finds_no_gpio_af_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "GD32F103.pdf"
            written_path = root / "chips/gigadevice/gd32f1/gd32f103/source/GD32F103_LQFP100_PINOUT.csv"
            candidate = crawler.DatasheetCandidate(
                part="GD32F103",
                url="https://download.gigadevice.com/Datasheet/GD32F103xx%20Datasheet_Rev3.3.pdf",
                source_url="https://www.gigadevice.com/product/mcu/gd32f103",
            )

            with (
                patch.object(crawler, "download_pdf", return_value=pdf_path),
                patch.object(crawler, "read_pdf_text", return_value="Table 2-6. LQFP100 pin definitions"),
                patch.object(crawler, "available_packages", return_value=["LQFP100"]),
                patch.object(crawler, "extract_gpio_af_rows", return_value=[]),
                patch.object(crawler, "write_package_csvs", return_value=[written_path]) as write_package_csvs,
            ):
                success = crawler.extract_candidate(candidate, root, root / "cache")

        self.assertEqual(success.function_source, "pinout-csv")
        write_package_csvs.assert_called_once_with(
            pdf_path,
            ["LQFP100"],
            root / "chips/gigadevice/gd32f1/gd32f103/source",
            "GD32F103",
            write_gpio_af=False,
            include_functions=True,
        )

    def test_extract_candidate_uses_pinout_functions_when_af_tokens_have_no_extractable_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "GD32F103.pdf"
            written_path = root / "chips/gigadevice/gd32f1/gd32f103/source/GD32F103_LQFP100_PINOUT.csv"
            candidate = crawler.DatasheetCandidate(
                part="GD32F103",
                url="https://download.gigadevice.com/Datasheet/GD32F103xx%20Datasheet_Rev3.3.pdf",
                source_url="https://www.gigadevice.com/product/mcu/gd32f103",
            )

            with (
                patch.object(crawler, "download_pdf", return_value=pdf_path),
                patch.object(crawler, "read_pdf_text", return_value="AF0 AF15 Table 2-6. LQFP100 pin definitions"),
                patch.object(crawler, "available_packages", return_value=["LQFP100"]),
                patch.object(crawler, "extract_gpio_af_rows", return_value=[]),
                patch.object(crawler, "write_package_csvs", return_value=[written_path]) as write_package_csvs,
            ):
                success = crawler.extract_candidate(candidate, root, root / "cache")

        self.assertEqual(success.function_source, "pinout-csv")
        write_package_csvs.assert_called_once_with(
            pdf_path,
            ["LQFP100"],
            root / "chips/gigadevice/gd32f1/gd32f103/source",
            "GD32F103",
            write_gpio_af=False,
            include_functions=True,
        )

    def test_extract_candidate_preserves_explicit_gpio_af_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "GD32F407.pdf"
            written_path = root / "chips/gigadevice/gd32f4/gd32f407/source/GD32F407_GPIO_AF.csv"
            candidate = crawler.DatasheetCandidate(
                part="GD32F407",
                url="https://download.gigadevice.com/Datasheet/GD32F407xx_Datasheet_Rev3.0.pdf",
                source_url="https://www.gigadevice.com/product/mcu/gd32f407",
            )

            with (
                patch.object(crawler, "download_pdf", return_value=pdf_path),
                patch.object(crawler, "read_pdf_text", return_value="Table 2-6. LQFP100 pin definitions"),
                patch.object(crawler, "available_packages", return_value=["LQFP100"]),
                patch.object(crawler, "extract_gpio_af_rows", return_value=[]),
                patch.object(crawler, "write_package_csvs", return_value=[written_path]) as write_package_csvs,
            ):
                success = crawler.extract_candidate(candidate, root, root / "cache", "gpio-af-csv")

        self.assertEqual(success.function_source, "gpio-af-csv")
        write_package_csvs.assert_called_once_with(
            pdf_path,
            ["LQFP100"],
            root / "chips/gigadevice/gd32f4/gd32f407/source",
            "GD32F407",
            write_gpio_af=True,
            include_functions=False,
        )

    def test_extract_candidate_reuses_auto_extracted_gpio_af_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "GD32F407.pdf"
            pinout_path = root / "chips/gigadevice/gd32f4/gd32f407/source/GD32F407_LQFP100_PINOUT.csv"
            candidate = crawler.DatasheetCandidate(
                part="GD32F407",
                url="https://download.gigadevice.com/Datasheet/GD32F407xx_Datasheet_Rev3.0.pdf",
                source_url="https://www.gigadevice.com/product/mcu/gd32f407",
            )

            with (
                patch.object(crawler, "download_pdf", return_value=pdf_path),
                patch.object(crawler, "read_pdf_text", return_value="Table 2-6. LQFP100 pin definitions"),
                patch.object(crawler, "available_packages", return_value=["LQFP100"]),
                patch.object(crawler, "extract_gpio_af_rows", return_value=[["PA0", *[""] * 16]]) as extract_gpio_af_rows,
                patch.object(crawler, "write_package_csvs", return_value=[pinout_path]) as write_package_csvs,
            ):
                success = crawler.extract_candidate(candidate, root, root / "cache")

            self.assertEqual(success.function_source, "gpio-af-csv")
            extract_gpio_af_rows.assert_called_once_with(pdf_path)
            write_package_csvs.assert_called_once_with(
                pdf_path,
                ["LQFP100"],
                root / "chips/gigadevice/gd32f4/gd32f407/source",
                "GD32F407",
                write_gpio_af=False,
                include_functions=False,
            )
            self.assertTrue(any(path.endswith("GD32F407_GPIO_AF.csv") for path in success.written_files))


if __name__ == "__main__":
    unittest.main()
