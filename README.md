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

## Publishing Updates

From the main McuPinFunc repository, add or update CSV files under:

`external-data/mcupinfunc-data/chips/<vendor>/<family>/<part>/source/`

You can extract CSV files from an official text PDF with:

```powershell
python tools/extract_pin_csv.py --pdf "GD32F407xx_Datasheet.pdf" --packages LQFP144,LQFP100
```

For a PDF URL:

```powershell
python tools/extract_pin_csv.py --pdf-url "https://example.com/GD32H759xx_Datasheet.pdf" --part GD32H759 --packages LQFP176
```

The tool writes directly to:

`chips/<vendor>/<family>/<part>/source/`

Then run:

```powershell
npm run validate:remote-data
npm run build:remote-data
npm run verify:remote-data
```

Expected outputs:

- per-chip `chip.json` files are updated,
- root `index.json` is updated,
- generated release data contains no duplicate packages or staging URLs,
- source CSV files remain in this data repository.

Commit and push from this repository:

```powershell
git status --short
git add .
git commit -m "data: add <chip-id>"
git push origin main
```

Verify the published index:

```text
https://raw.githubusercontent.com/GYM-png/mcupinfunc-data/main/index.json
```
