# McuPinFunc Data

This repository stores source CSV files and generated chip data packs for McuPinFunc.

McuPinFunc downloads only the selected chip's `chip.json` at runtime. Source CSV files are kept here for maintenance, review, and local import workflows.

## Layout

`index.json` is the searchable remote chip registry.

Each chip lives under:

`chips/<vendor>/<family>/<part>/`

Runtime data:

`chip.json`

Source CSV data:

`source/<PART>_GPIO_AF.csv`
`source/<PART>_<PACKAGE>_PINOUT.csv`
