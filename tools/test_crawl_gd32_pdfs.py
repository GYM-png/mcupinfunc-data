import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import crawl_gd32_pdfs as crawler


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


if __name__ == "__main__":
    unittest.main()
