import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_pin_csv as extractor


class ExtractPinCsvTest(unittest.TestCase):
    def test_extracts_alternate_and_remap_from_pin_definition_rows(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        GD32F103Vx LQFP100
        Pin I/O
        Pin Name Pins Functions description
        Type(1) Level(2)
        Default: PA4
        Alternate: SPI0_NSS, USART1_CK, ADC01_IN4,
        PA4 29 I/O
        DAC0_OUT0
        Remap:SPI2_NSS, I2S2_WS
        Default: PA5
        PA5 30 I/O
        Alternate: SPI0_SCK, ADC01_IN5, DAC0_OUT1
        VSS_4 31 P Default: VSS_4
        VDD_4 32 P Default: VDD_4
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        csv_text = extractor.rows_to_csv_text(rows, "LQFP100", include_functions=True)

        self.assertIn("PadNumber,PinName,PinType,Alternate,Remap", csv_text.splitlines()[0])
        self.assertIn("29,PA4,gpio,SPI0_NSS/USART1_CK/ADC01_IN4/DAC0_OUT0,SPI2_NSS/I2S2_WS", csv_text)
        self.assertIn("30,PA5,gpio,SPI0_SCK/ADC01_IN5/DAC0_OUT1,", csv_text)

    def test_default_csv_output_stays_three_columns(self) -> None:
        rows = [extractor.PinRow(29, "PA4", "gpio", "SPI0_NSS", "SPI2_NSS")]

        csv_text = extractor.rows_to_csv_text(rows, "LQFP100")

        self.assertEqual(csv_text, "PadNumber,PinName,PinType\n29,PA4,gpio\n")


if __name__ == "__main__":
    unittest.main()
