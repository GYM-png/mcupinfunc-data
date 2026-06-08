import sys
import tempfile
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

    def test_download_pdf_reuses_readable_cached_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            cached_pdf = cache_dir / "GD32A513xx_Datasheet_Rev1.4.pdf"
            cached_pdf.write_bytes(b"%PDF cached")
            original_urlretrieve = extractor.urllib.request.urlretrieve

            def fail_if_called(url: str, filename: Path) -> None:
                raise AssertionError("download should not be attempted when cached PDF is readable")

            extractor.urllib.request.urlretrieve = fail_if_called
            try:
                result = extractor.download_pdf(
                    "https://download.gigadevice.com/Datasheet/GD32A513xx_Datasheet_Rev1.4.pdf",
                    cache_dir=cache_dir,
                )
            finally:
                extractor.urllib.request.urlretrieve = original_urlretrieve

        self.assertEqual(result, cached_pdf)

    def test_classifies_gpio_named_input_and_output_rows_as_gpio(self) -> None:
        self.assertEqual(extractor.classify_pin("PA0", "I"), "gpio")
        self.assertEqual(extractor.classify_pin("PB1", "O"), "gpio")
        self.assertEqual(extractor.classify_pin("PC13-OSC32IN", "I"), "gpio")
        self.assertEqual(extractor.classify_pin("PC13-TAMPER-RTC", "P"), "gpio")
        self.assertEqual(extractor.classify_pin("PC2_C", "I/O"), "gpio")

    def test_accepts_clock_reset_boot_and_vref_package_pin_names(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP144 pin definitions
        Table 2-6. GD32F103Vx LQFP144 pin definitions
        Pin Name Pins Functions description
        OSCIN-PD0 12 I
        Default: OSCIN
        Remap: PD0
        OSCOUT-
        PD1
        13 O
        Default: OSCOUT
        Remap: PD1
        NRST-PG10 14 I/O
        Default: NRST
        BOOT1-PB2 21 I/O
        Default: BOOT1
        VREF- 22 P
        Default: VREF-
        VSS_10 120   Default: VSS_10
        VDD_10 121   Default: VDD_10
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP144", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[12].pin_name, "OSCIN-PD0")
        self.assertEqual(by_pad[12].pin_type, "clock")
        self.assertEqual(by_pad[13].pin_name, "OSCOUT-PD1")
        self.assertEqual(by_pad[13].pin_type, "clock")
        self.assertEqual(by_pad[14].pin_name, "NRST-PG10")
        self.assertEqual(by_pad[14].pin_type, "reset")
        self.assertEqual(by_pad[21].pin_name, "BOOT1-PB2")
        self.assertEqual(by_pad[21].pin_type, "boot")
        self.assertEqual(by_pad[22].pin_name, "VREF-")
        self.assertEqual(by_pad[22].pin_type, "power")
        self.assertEqual(by_pad[120].pin_name, "VSS_10")
        self.assertEqual(by_pad[120].pin_type, "ground")
        self.assertEqual(by_pad[121].pin_name, "VDD_10")
        self.assertEqual(by_pad[121].pin_type, "power")

    def test_lqfp_rows_ignore_bga_ball_positions(self) -> None:
        text = """
        2.6.2. GD32L233Cx LQFP48 pin definitions
        Table 2-5. GD32L233Cx LQFP48 pin definitions
        Pin Name Pins Functions description
        VBAT 1 P
        PC13 2 I/O
        PB9 48 I/O
        VDD A1 P
        PA14 A2 I/O
        VSS A6 P
        2.6.5. GD32L233Kx
        """

        rows = extractor.extract_package_rows(text, "LQFP48", include_functions=True)

        self.assertEqual([row.pad_number for row in rows], [1, 2, 48])

    def test_find_section_skips_table_of_contents_entries(self) -> None:
        text = """
        2.6.3. GD32A513Cx LQFP48 pin definitions ................................................................ 32
        2.6.4. GD32A513Kx QFN32 pin definitions .................................................................. 36
        3. Functional description ..................................................................................... 45
        2
        Table 2-4. GD32A513Rx LQFP64 pin definitions
        GD32A513Rx LQFP64
        PA0 1 I/O
        Table 2-5. GD32A513Cx LQFP48 pin definitions
        GD32A513Cx LQFP48
        Pin Name Pins Functions description
        PE4 1 I/O
        PE5 2 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP48", include_functions=True)

        self.assertEqual([row.pad_number for row in rows], [1, 2])

    def test_find_section_skips_toc_entry_with_unrelated_numeric_table_rows(self) -> None:
        text = """
        Table 2-5. GD32A513Cx LQFP48 pin definitions ................................................................ 32
        Table 2-6. GD32A513Kx QFN32 pin definitions ................................................................ 36
        2. Device overview
        Part Number
        PB12 51
        PE2 75
        VDD_1 PA14 76
        2.6.3. GD32A513Cx LQFP48 pin definitions
        Table 2-5. GD32A513Cx LQFP48 pin definitions
        GD32A513Cx LQFP48
        Pin Name Pins
        PE4 1 I/O
        PE5 2 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP48", include_functions=True)

        self.assertEqual([row.pad_number for row in rows], [1, 2])

    def test_find_section_accepts_split_pin_name_header(self) -> None:
        text = """
        Table 2-3. GD32F207Ix LQFP176 pin definitions ................................................................ 20
        2.6.1. GD32F207Ix LQFP176 pin definitions
        Table 2-3. GD32F207Ix LQFP176 pin definitions
        GD32F207Ix LQFP176
        Pin
        Name
        Pins
        Pin
        Type(1)
        I/O
        Level(2)
        Functions description
        PE2 1 I/O 5VT
        Default: PE2
        Alternate: TRACECK, EXMC_A23
        2.6.2. GD32F207Zx LQFP144 pin definitions
        """

        rows = extractor.extract_package_rows(text, "LQFP176", include_functions=True)

        self.assertEqual(rows[0].pad_number, 1)
        self.assertEqual(rows[0].pin_name, "PE2")

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

    def test_different_default_after_active_row_starts_next_pre_row_block(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        PA4 29 I/O
        Default: PA4
        Alternate: SPI0_NSS
        Default: PA5
        Alternate: SPI0_SCK
        PA5 30 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pin_name = {row.pin_name: row for row in rows}

        self.assertEqual(by_pin_name["PA4"].alternate, "SPI0_NSS")
        self.assertEqual(by_pin_name["PA5"].alternate, "SPI0_SCK")

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

    def test_discards_pre_row_functions_for_non_gpio_pin(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        Default: VSS_4
        Alternate: SHOULD_NOT_ATTACH
        VSS_4 30 P
        PA5 31 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        csv_text = extractor.rows_to_csv_text(rows, "LQFP100", include_functions=True)
        by_pin_name = {row.pin_name: row for row in rows}

        self.assertEqual(by_pin_name["VSS_4"].alternate, "")
        self.assertEqual(by_pin_name["VSS_4"].remap, "")
        self.assertEqual(by_pin_name["PA5"].alternate, "")
        self.assertNotIn("SHOULD_NOT_ATTACH", csv_text)

    def test_bare_function_after_non_gpio_row_does_not_attach_to_next_gpio(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        VSS_4 30 P
        Alternate: SHOULD_NOT_ATTACH
        PA5 31 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        csv_text = extractor.rows_to_csv_text(rows, "LQFP100", include_functions=True)
        by_pin_name = {row.pin_name: row for row in rows}

        self.assertEqual(by_pin_name["PA5"].alternate, "")
        self.assertNotIn("SHOULD_NOT_ATTACH", csv_text)

    def test_product_title_stops_function_continuation(self) -> None:
        text = """
        2.6.2. GD32F103Vx LQFP100 pin definitions
        Table 2-6. GD32F103Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        Default: PA4
        Alternate: SPI0_NSS,
        GD32F103Vx LQFP100
        USART1_CK
        PA4 29 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pin_name = {row.pin_name: row for row in rows}
        csv_text = extractor.rows_to_csv_text(rows, "LQFP100", include_functions=True)

        self.assertEqual(by_pin_name["PA4"].alternate, "SPI0_NSS")
        self.assertNotIn("GD32F103Vx LQFP100", csv_text)
        self.assertNotIn("USART1_CK", csv_text)

    def test_orphan_function_word_does_not_pollute_wrapped_pin_name(self) -> None:
        text = """
        2.6.2. GD32A513Vx LQFP100 pin definitions
        Table 2-6. GD32A513Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        PE6 5 I/O
        Default: PE6
        Alternate: TIMER1_CH0, TIMER1_ETI, TIMER19_MCH
        2, I2S1_MCK, MFCOM_D5, TRIGSEL_OUT5, EVENT
        OUT
        PC13-
        OSC32IN
        6 I/O
        Default: PC13
        Alternate: CK_OUT, TIMER19_CH2, MFCOM_D4,
        TRIGSEL_OUT4, EVENTOUT
        Additional: WKUP1, OSC32IN
        PC14-
        OSC32IN
        7 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(
            by_pad[5].alternate,
            "TIMER1_CH0/TIMER1_ETI/TIMER19_MCH2/I2S1_MCK/MFCOM_D5/TRIGSEL_OUT5/EVENTOUT",
        )
        self.assertEqual(by_pad[6].pin_name, "PC13-OSC32IN")
        self.assertEqual(by_pad[6].pin_type, "gpio")
        self.assertEqual(
            by_pad[6].alternate,
            "CK_OUT/TIMER19_CH2/MFCOM_D4/TRIGSEL_OUT4/EVENTOUT/WKUP1/OSC32IN",
        )
        self.assertEqual(by_pad[7].pin_name, "PC14-OSC32IN")

    def test_keeps_multi_fragment_wrapped_gpio_pin_names(self) -> None:
        text = """
        2.6.2. GD32F403Vx LQFP100 pin definitions
        Table 2-6. GD32F403Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        VBAT 6 P
        PC13-
        TAMPER-
        RTC
        7 I/O Default: PC13
        Alternate: TAMPER-RTC
        PC14-
        OSC32IN
        8 I/O Default: PC14
        Alternate: OSC32IN
        PC15-
        OSC32OU
        T
        9 I/O Default: PC15
        Alternate: OSC32OUT
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[7].pin_name, "PC13-TAMPER-RTC")
        self.assertEqual(by_pad[7].pin_type, "gpio")
        self.assertEqual(by_pad[7].alternate, "TAMPER-RTC")
        self.assertEqual(by_pad[8].pin_name, "PC14-OSC32IN")
        self.assertEqual(by_pad[8].pin_type, "gpio")
        self.assertEqual(by_pad[8].alternate, "OSC32IN")
        self.assertEqual(by_pad[9].pin_name, "PC15-OSC32OUT")
        self.assertEqual(by_pad[9].pin_type, "gpio")
        self.assertEqual(by_pad[9].alternate, "OSC32OUT")

    def test_keeps_multi_fragment_wrapped_bga_pin_names(self) -> None:
        text = """
        2.6.2. GD32F403Vx BGA100 pin definitions
        Table 2-7. GD32F403Vx BGA100 pin definitions
        Pin Name Pins Functions description
        VBAT E2 P Default: VBAT
        PC13-
        TAMPER-
        RTC
        C1 I/O Default: PC13
        Alternate: TAMPER-RTC
        PC14-
        OSC32IN
        D1 I/O Default: PC14
        Alternate: OSC32IN
        PC15-
        OSC32OU
        T
        E1 I/O Default: PC15
        Alternate: OSC32OUT
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "BGA100", include_functions=True)
        by_ball = {row.pad_number: row for row in rows}

        self.assertEqual(by_ball["C1"].pin_name, "PC13-TAMPER-RTC")
        self.assertEqual(by_ball["C1"].pin_type, "gpio")
        self.assertEqual(by_ball["C1"].alternate, "TAMPER-RTC")
        self.assertEqual(by_ball["D1"].pin_name, "PC14-OSC32IN")
        self.assertEqual(by_ball["D1"].alternate, "OSC32IN")
        self.assertEqual(by_ball["E1"].pin_name, "PC15-OSC32OUT")
        self.assertEqual(by_ball["E1"].alternate, "OSC32OUT")

    def test_bga_page_break_suffix_does_not_pollute_next_wrapped_pin(self) -> None:
        text = """
        2.6.2. GD32F405Vx BGA100 pin definitions
        Table 2-5. GD32F405Vx BGA100 pin definitions
        Pin Name Pins Functions description
        PC13-
        TAMPER-
        C1 I/O 5VT
        Default: PC13
        Alternate: EVENTOUT
        GD32F405xx Datasheet
        GD32F405Vx BGA100
        Pin Name Pins
        RTC Additional: RTC_TAMP0, RTC_OUT, RTC_TS
        PC14-
        OSC32IN
        D1 I/O 5VT
        Default: PC14
        Additional: OSC32IN
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "BGA100", include_functions=True)
        by_ball = {row.pad_number: row for row in rows}

        self.assertEqual(by_ball["C1"].pin_name, "PC13-TAMPER-RTC")
        self.assertEqual(by_ball["C1"].alternate, "EVENTOUT/RTC_TAMP0/RTC_OUT/RTC_TS")
        self.assertEqual(by_ball["D1"].pin_name, "PC14-OSC32IN")
        self.assertEqual(by_ball["D1"].alternate, "OSC32IN")

    def test_joins_pending_name_with_inline_fragment_before_position(self) -> None:
        text = """
        2.6.2. GD32F105Vx LQFP100 pin definitions
        Table 2-6. GD32F105Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        VREFP 21 P Default: VREFP
        VDDA 22 P Default: VDDA
        PA0-
        WKUP 23 I/O
        Default: PA0
        Alternate: WKUP, USART1_CTS, ADC01_IN0,
        TIMER1_CH0, TIMER1_ETI, TIMER4_CH0
        PA1 24 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[23].pin_name, "PA0-WKUP")
        self.assertEqual(by_pad[23].pin_type, "gpio")
        self.assertEqual(by_pad[23].alternate, "WKUP/USART1_CTS/ADC01_IN0/TIMER1_CH0/TIMER1_ETI/TIMER4_CH0")

    def test_lqfp_joins_wrapped_clock_name_before_inline_gpio_fragment(self) -> None:
        text = """
        2.6.2. GD32F105Vx LQFP100 pin definitions
        Table 2-6. GD32F105Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        OSCOUT-
        PD1 13 O Default: OSCOUT
        Remap: PD1
        NRST 14 I/O Default: NRST
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[13].pin_name, "OSCOUT-PD1")
        self.assertEqual(by_pad[13].pin_type, "clock")
        self.assertEqual(by_pad[13].remap, "PD1")

    def test_function_fragment_named_ventout_does_not_pollute_next_lqfp_row(self) -> None:
        text = """
        2.6.2. GD32L233Cx LQFP48 pin definitions
        Table 2-6. GD32L233Cx LQFP48 pin definitions
        Pin Name Pins Functions description
        PC11 39 I/O 5VT
        Default: PC11
        Alternate: UART3_RX, E
        VENTOUT
        PC12 40 I/O 5VT
        Default: PC12
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP48", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[39].alternate, "UART3_RX/E/VENTOUT")
        self.assertEqual(by_pad[40].pin_name, "PC12")

    def test_accepts_gpio_pin_names_with_suffixes(self) -> None:
        text = """
        2.6.2. GD32H757Vx LQFP100 pin definitions
        Table 2-6. GD32H757Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        PC2_C 17 I/O Default: PC2_C(4)
        Additional: ADC2_IN0
        PC3_C 18 I/O Default: PC3_C(4)
        Additional: ADC2_IN1
        VSSA 19 P - Default: VSSA
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[17].pin_name, "PC2_C")
        self.assertEqual(by_pad[17].pin_type, "gpio")
        self.assertEqual(by_pad[17].alternate, "ADC2_IN0")
        self.assertEqual(by_pad[18].pin_name, "PC3_C")
        self.assertEqual(by_pad[18].pin_type, "gpio")
        self.assertEqual(by_pad[18].alternate, "ADC2_IN1")

    def test_accepts_wrapped_usb_differential_pin_names(self) -> None:
        text = """
        2.6.2. GD32H757Vx LQFP100 pin definitions
        Table 2-6. GD32H757Vx LQFP100 pin definitions
        Pin Name Pins Functions description
        PA10 69 I/O 5VT
        Default: PA10
        USBHS0_
        DM
        70 I/O Default: USBHS0_DM(3)
        USBHS0_
        DP
        71 I/O Default: USBHS0_DP(3)
        PA13 72 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP100", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[70].pin_name, "USBHS0_DM")
        self.assertEqual(by_pad[70].pin_type, "gpio")
        self.assertEqual(by_pad[71].pin_name, "USBHS0_DP")
        self.assertEqual(by_pad[71].pin_type, "gpio")

    def test_bga176_ignores_center_additional_vss_array(self) -> None:
        rows = [
            extractor.PinRow("E5", "PA0", "gpio"),
            extractor.PinRow("F6", "VSS", "ground"),
            extractor.PinRow("F7", "VSS", "ground"),
            extractor.PinRow("G6", "VSS", "ground"),
            extractor.PinRow("K10", "VSS", "ground"),
            extractor.PinRow("R15", "VSS", "ground"),
        ]

        filtered = extractor.filter_package_rows(rows, "BGA176")

        self.assertEqual([row.pad_number for row in filtered], ["E5", "R15"])

    def test_bga_filters_gpio_names_misread_as_ball_positions(self) -> None:
        rows = [
            extractor.PinRow("A11", "PA13", "gpio"),
            extractor.PinRow("PA13", "USBFS_DP", "other"),
        ]

        filtered = extractor.filter_package_rows(rows, "BGA100")

        self.assertEqual([row.pad_number for row in filtered], ["A11"])

    def test_bga_ignores_remap_gpio_token_misread_as_ball_position(self) -> None:
        text = """
        2.6.2. GD32F403Vx BGA100 pin definitions
        Table 2-7. GD32F403Vx BGA100 pin definitions
        Pin Name Pins Functions description
        PA13 A11 I/O 5VT Default: JTMS, SWDIO
        Remap: PA13
        NC C11 - -
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "BGA100", include_functions=True)
        by_ball = {row.pad_number: row for row in rows}

        self.assertEqual(by_ball["A11"].pin_name, "PA13")
        self.assertEqual(by_ball["A11"].remap, "PA13")
        self.assertNotIn("PA13", by_ball)

    def test_bga_inline_gpio_name_before_ball_position_prefers_ball_position(self) -> None:
        text = """
        2.6.2. GD32F403Vx BGA100 pin definitions
        Table 2-7. GD32F403Vx BGA100 pin definitions
        Pin Name Pins Functions description
        PA13 A11 I/O 5VT Default: JTMS, SWDIO
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "BGA100", include_functions=True)
        by_ball = {row.pad_number: row for row in rows}

        self.assertEqual(by_ball["A11"].pin_name, "PA13")
        self.assertEqual(by_ball["A11"].pin_type, "gpio")
        self.assertNotIn("PA13", by_ball)

    def test_bga_function_fragment_before_inline_row_does_not_become_pending_pin_name(self) -> None:
        text = """
        2.6.2. GD32F403Vx BGA100 pin definitions
        Table 2-7. GD32F403Vx BGA100 pin definitions
        Pin Name Pins Functions description
        PA12 A12 I/O 5VT
        Default: PA12
        Alternate: USART0_RTS, CAN0_TX,
        USBFS_DP
        PA13 A11 I/O 5VT Default: JTMS, SWDIO
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "BGA100", include_functions=True)
        by_ball = {row.pad_number: row for row in rows}

        self.assertEqual(by_ball["A12"].alternate, "USART0_RTS/CAN0_TX/USBFS_DP")
        self.assertEqual(by_ball["A11"].pin_name, "PA13")

    def test_keeps_wrapped_slash_separated_power_names(self) -> None:
        text = """
        2.6.2. GD32C231Kx LQFP32 pin definitions
        Table 2-6. GD32C231Kx LQFP32 pin definitions
        Pin Name Pins Functions description
        VDD/VDDA/V
        REFP
        4 P -
        Default: VDD /VDDA/VREFP
        VSS/VSSA/V
        REFN
        5 P -
        Default: VSS /VSSA/VREFN
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP32", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[4].pin_name, "VDD/VDDA/VREFP")
        self.assertEqual(by_pad[4].pin_type, "power")
        self.assertEqual(by_pad[5].pin_name, "VSS/VSSA/VREFN")
        self.assertEqual(by_pad[5].pin_type, "ground")

    def test_accepts_h7_smps_power_names(self) -> None:
        text = """
        2.6.2. GD32H759Ix LQFP176 pin definitions
        Table 2-6. GD32H759Ix LQFP176 pin definitions
        Pin Name Pins Functions description
        VLXSMPS 15 P - Default: VLXSMPS
        VDDSMPS 16 P - Default: VDDSMPS
        VFBSMPS 17 P - Default: VFBSMPS
        PF0 18 I/O
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP176", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[15].pin_type, "power")
        self.assertEqual(by_pad[16].pin_type, "power")
        self.assertEqual(by_pad[17].pin_type, "power")

    def test_lqfp_ignores_numeric_rows_outside_package_pad_count(self) -> None:
        text = """
        2.6.2. GD32F103Cx LQFP48 pin definitions
        Table 2-6. GD32F103Cx LQFP48 pin definitions
        Pin Name Pins Functions description
        PA0 10 I/O
        VDDGND 100 P
        2.7. Memory map
        """

        rows = extractor.extract_package_rows(text, "LQFP48", include_functions=True)

        self.assertEqual([row.pad_number for row in rows], [10])

    def test_lqfp_fills_single_missing_ground_before_power_pin(self) -> None:
        rows = [
            extractor.PinRow(46, "PA13", "gpio"),
            extractor.PinRow(48, "VDD", "power"),
            extractor.PinRow(49, "PA14", "gpio"),
        ]

        filtered = extractor.filter_package_rows(rows, "LQFP64")
        by_pad = {row.pad_number: row for row in filtered}

        self.assertEqual(by_pad[47].pin_name, "VSS")
        self.assertEqual(by_pad[47].pin_type, "ground")
        self.assertEqual([row.pad_number for row in filtered], [46, 47, 48, 49])

    def test_lqfp_keeps_split_clock_name_before_position_row(self) -> None:
        text = """
        2.6.1. GD32F207Ix LQFP176 pin definitions
        Table 2-3. GD32F207Ix LQFP176 pin definitions
        GD32F207Ix LQFP176
        Pin
        Name
        Pins
        Pin
        Type(1)
        I/O
        Level(2)
        Functions description
        OSCIN 29 I Default: OSCIN
        Remap: PD0, PH0
        OSCO
        UT
        30 O Default: OSCOUT
        Remap: PD1, PH1
        NRST 31 I/O Default: NRST
        2.6.2. GD32F207Zx LQFP144 pin definitions
        """

        rows = extractor.extract_package_rows(text, "LQFP176", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[29].pin_name, "OSCIN")
        self.assertEqual(by_pad[29].remap, "PD0/PH0")
        self.assertEqual(by_pad[30].pin_name, "OSCOUT")
        self.assertEqual(by_pad[30].pin_type, "clock")
        self.assertEqual(by_pad[30].remap, "PD1/PH1")

    def test_lqfp_joins_split_power_suffix_before_position_row(self) -> None:
        text = """
        2.6.1. GD32F207Ix LQFP176 pin definitions
        Table 2-3. GD32F207Ix LQFP176 pin definitions
        GD32F207Ix LQFP176
        Pin
        Name
        Pins
        Pin
        Type(1)
        I/O
        Level(2)
        Functions description
        PD5 147 I/O 5VT
        Default: PD5
        VSS_1
        0
        148 P Default: VSS_10
        VDD_1
        0
        149 P Default: VDD_10
        PD6 150 I/O 5VT
        2.6.2. GD32F207Zx LQFP144 pin definitions
        """

        rows = extractor.extract_package_rows(text, "LQFP176", include_functions=True)
        by_pad = {row.pad_number: row for row in rows}

        self.assertEqual(by_pad[148].pin_name, "VSS_10")
        self.assertEqual(by_pad[148].pin_type, "ground")
        self.assertEqual(by_pad[149].pin_name, "VDD_10")
        self.assertEqual(by_pad[149].pin_type, "power")


if __name__ == "__main__":
    unittest.main()
