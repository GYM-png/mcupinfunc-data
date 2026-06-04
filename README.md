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

Then run:

```powershell
npm run validate:remote-data
npm run build:remote-data
```

Expected outputs:

- per-chip `chip.json` files are updated,
- root `index.json` is updated,
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
