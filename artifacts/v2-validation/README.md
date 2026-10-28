# V2 validation evidence

- automated-tests.json: complete backend suite, 100 passing tests; paid live requests are excluded.
- live-codex.json: real ChatGPT-plan modelling, selected-scope preservation, session continuation, undo/redo and text creation/refinement.
- live-cancellation.json: real provider turn interrupted after changing candidate geometry; accepted revision preserved.
- live-viewport.json: real viewport-image input plus explicit selection; inspection left geometry unchanged.
- ui.json and the screenshots: real native rendering/picking of procedural test fixtures at recorded sizes and device-pixel ratios. These are not image-service outputs.
- packaged.json: isolated bundled-runtime checks and installer metadata.

Image-service HTTP tests use a fixture transport. A paid Tripo generation was deferred by the user and has not been represented as complete. Screenshots use isolated example projects without connected account details. Raw diagnostic logs and transient CAD/provider sessions remain local in ignored workspace directories.
