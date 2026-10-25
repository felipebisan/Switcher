# Road geometry provenance

This local minimap uses the 457 road polylines from:
https://github.com/atikhobaev/fh6-scenic-navigator/blob/main/static/data/fh6_roads.json
Upstream geometry source: https://forza.labsgg.com/interactive-map

The data was aligned to the existing screenshot atlas using an affine transform, retaining the user's world calibration. Source coordinates (x,y) become atlas coordinates:
x' = 1.2627098552732217*x + 0.000029287372178624094*y - 117.08738326679637
y' = -0.0000726424796588269*x + 1.2630131410371452*y - 113.15259807120763

The source's MIT license applies to its original code, not this third-party geometry. Redistribution permission is not established. Review upstream LICENSE_SCOPE.md before packaging these data for others. No upstream executable or program code was run.

The transparent minimap uses this geometry; Dark and Original map styles still use the user's screenshots. Existing calibration and group settings are preserved. Road coverage and live game alignment require in-game verification.
