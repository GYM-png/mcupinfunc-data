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
        Alternate: SPI0_NSS(1), USART1_CK, ADC01_IN4,
        PA4 29 I/O
        DAC0_OUT0
        Remap:SPI2_NSS, I2S2_WS, TIMER8_CH0(3)
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
        self.assertIn("29,PA4,gpio,SPI0_NSS/USART1_CK/ADC01_IN4/DAC0_OUT0,SPI2_NSS/I2S2_WS/TIMER8_CH0", csv_text)
        self.assertNotIn("SPI0_NSS(1)", csv_text)
        self.assertNotIn("TIMER8_CH0(3)", csv_text)
        self.assertIn("30,PA5,gpio,SPI0_SCK/ADC01_IN5/DAC0_OUT1,", csv_text)

    def test_default_csv_output_stays_three_columns(self) -> None:
        rows = [extractor.PinRow(29, "PA4", "gpio", "SPI0_NSS", "SPI2_NSS")]

        csv_text = extractor.rows_to_csv_text(rows, "LQFP100")

        self.assertEqual(csv_text, "PadNumber,PinName,PinType\n29,PA4,gpio\n")

    def test_keeps_wrapped_function_text_before_pin_row(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        Default: PA4
        Alternate: SPI0_NSS, USART1_CK,
        ADC01_IN4
        PA4 29 I/O
        VSS_4 30 P Default: VSS_4
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)

        self.assertEqual(rows[0].alternate, "SPI0_NSS/USART1_CK/ADC01_IN4")

    def test_attaches_row_first_functions_to_active_pin_row(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        PA4 29 I/O
        Default: PA4
        Alternate: SPI0_NSS, USART1_CK, ADC01_IN4,
        DAC0_OUT0(4)
        Remap:SPI2_NSS(4), I2S2_WS(4)
        PA5 30 I/O
        Default: PA5
        Alternate: SPI0_SCK, ADC01_IN5, DAC0_OUT1
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pin_name = {row.pin_name: row for row in rows}

        self.assertEqual(by_pin_name["PA4"].alternate, "SPI0_NSS/USART1_CK/ADC01_IN4/DAC0_OUT0")
        self.assertEqual(by_pin_name["PA4"].remap, "SPI2_NSS/I2S2_WS")
        self.assertEqual(by_pin_name["PA5"].alternate, "SPI0_SCK/ADC01_IN5/DAC0_OUT1")
        self.assertEqual(by_pin_name["PA5"].remap, "")
        self.assertNotIn("SPI0_NSS", by_pin_name["PA5"].alternate)
        self.assertNotIn("SPI2_NSS", by_pin_name["PA5"].remap)

    def test_ignores_table_text_after_default_non_gpio_row(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        Default: PA4
        Alternate: SPI0_NSS, USART1_CK,
        PA4 29 I/O
        DAC0_OUT0
        VSS_4 30 P Default: VSS_4
        Table 2-6. continued
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        csv_text = extractor.rows_to_csv_text(rows, "LQFP100", include_functions=True)

        self.assertIn("29,PA4,gpio,SPI0_NSS/USART1_CK/DAC0_OUT0,", csv_text)
        self.assertIn("30,VSS_4,ground,,", csv_text)
        self.assertNotIn("Table 2-6. continued", csv_text)


if __name__ == "__main__":
    unittest.main()
