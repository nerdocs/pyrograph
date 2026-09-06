# pyrograph

Open laser engraving software: design, position and engrave. Built on the `laserpecker` driver.

The document model, the SVG import, job creation and the device abstraction work, and a command line drives
them end to end:

```bash
pyrograph import drawing.svg drawing.pyg
pyrograph --mock engrave drawing.pyg
```

`--mock` runs everything against a device that only exists in memory. The GUI has not been started.
