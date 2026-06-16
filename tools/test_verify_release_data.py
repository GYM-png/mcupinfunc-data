import json
import tempfile
import unittest
from pathlib import Path

import verify_release_data as verifier


class VerifyReleaseDataTest(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    def test_reports_duplicate_index_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_json(
                root / "index.json",
                {
                    "chips": [
                        {
                            "id": "GD32F470",
                            "packages": ["BGA100", "BGA100"],
                            "chipUrl": "https://raw.githubusercontent.com/GYM-png/mcupinfunc-data/main/chips/gigadevice/gd32f4/gd32f470/chip.json",
                            "sourceFiles": [],
                        }
                    ]
                },
            )

            errors = verifier.verify_release_data(root)

            self.assertEqual(errors, ["index chip GD32F470 has duplicate package BGA100"])

    def test_reports_staging_urls_in_index_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_json(
                root / "index.json",
                {
                    "chips": [
                        {
                            "id": "GD32F470",
                            "packages": ["BGA100"],
                            "chipUrl": "https://raw.githubusercontent.com/GYM-png/mcupinfunc-data/main/chips/gigadevice/gd32f4/gd32f470/chip.json",
                            "sourceFiles": [
                                {
                                    "type": "pinout",
                                    "package": "BGA100",
                                    "url": "https://raw.githubusercontent.com/GYM-png/mcupinfunc-data/main/staging/gd32-csv-export/chips/gigadevice/gd32f4/gd32f470/source/GD32F470_BGA100_PINOUT.csv",
                                }
                            ],
                        }
                    ]
                },
            )

            errors = verifier.verify_release_data(root)

            self.assertEqual(errors, ["index chip GD32F470 source file URL points at staging: BGA100"])

    def test_reports_duplicate_chip_json_package_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_json(root / "index.json", {"chips": []})
            self.write_json(
                root / "chips/gigadevice/gd32f4/gd32f470/chip.json",
                {
                    "id": "GD32F470",
                    "packages": [
                        {"packageName": "BGA100"},
                        {"packageName": "BGA100"},
                    ],
                },
            )

            errors = verifier.verify_release_data(root)

            self.assertEqual(errors, ["chip.json GD32F470 has duplicate package BGA100"])


if __name__ == "__main__":
    unittest.main()
