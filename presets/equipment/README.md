# Equipment presets

The gear offered by "Start from a preset" in the Equipment tab and the setup wizard: one file per
gear type and manufacturer (`telescopes/zwo.json`, `cameras/canon.json`...).

1. Edit or create the file of the type and manufacturer. Keep the `$schema` line: your editor then
   completes the keys and underlines mistakes.
2. Run `python scripts/build_equipment_presets.py`. It formats the files, rebuilds
   `static/data/equipment_presets.json` and lists every problem to fix.
3. Commit the preset files and the generated files together.

Every value comes from the maker's official spec page, given in `source_url`. Rules, keys and the
smart telescope bundles: [docs/EQUIPMENT.md](../../docs/EQUIPMENT.md#presets).
