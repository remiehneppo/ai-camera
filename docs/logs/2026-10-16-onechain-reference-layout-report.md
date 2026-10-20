# AI Camera research report — OneChain reference layout, 2026-10-16

## Scope and decisions

- User authorized LibreOffice for the Design Report task after the advertised document workflow was unavailable, then supplied `bao-cao-chon-model-lan-1.pdf` as the layout reference. No application UI changes were made.
- Read the research report, source registry, price observations, research criteria and outline. Consulted CodeGraph for runtime/pipeline/detector/tracker/pose context; read the identified implementation files and historical oracle/replay evidence. Source snapshot: `6fff369f4c30dd6faff0150b660cf5e065207daa` plus existing working tree.
- Report is self-contained: research, optical/ODD considerations, algorithms, architecture, data/evaluation, hardware and historical cost observations, preliminary implementation and replay results, tradeoffs, recommendations and next steps. Omitted unit-test counts. Separated implementation, historical measurements, targets and unaccepted recommendations.
- Retained the Design Report DOCX reference unchanged. The user's later PDF explicitly overrides its layout: A4, centered corporate cover, original embedded OneChain logo, version history, numbered headings, amber rules, company footer and page numbers. Preserved Google Sans Flex and readable ink text on amber, and white/neutral surfaces per the supplied OneChain specification rather than copying the sample's serif font, white text on amber or cream table fill.
- Extracted existing logo images from the supplied PDF without redrawing/recoloring. Moved the previous cover architecture illustration into the architecture section. Kept both charts with numeric labels, units and min–max legends based on the existing twelve replay measurements.
- Downloaded the official Google Sans Flex variable font to temporary storage; created 400/500/600/700 export instances locally for LibreOffice. No system font installation or application dependency changes.
- Rechecked official ONNX Runtime profiling/threading, SQLite WAL-reset and FFmpeg segment documentation for technical recommendations. Historical market/legal observations remain dated research inputs; no current-price, purchase or legal clearance claim.

## Deliverables

Directory: `docs/reports/2026-10-16-onechain-reference-layout/`.

- `AI-Camera-Research-Report-OneChain-2026-10-16.pdf`: checked sharing artifact, 48 A4 pages.
- `AI-Camera-Research-Report-OneChain-2026-10-16.docx`: editable report.
- `report-content.md`: full synthesis; unchanged during the final layout revision.
- Two replay chart PNGs and `build-manifest.json` with source/reference/output hashes and validation evidence.

## Verification

- Exported using isolated headless LibreOffice 24.2 with UNO; regenerated the table of contents.
- Compared every research paragraph before/after layout revision: all preserved. The Markdown content is byte-identical between the prior and final layout directories.
- PDF font inventory contains only Google Sans Flex Regular/Medium/SemiBold/Bold, all embedded. Tagged PDF, A4, no encryption.
- Rendered all 48 pages and visually inspected all four contact sheets plus full-size cover, contents and body previews. Checked tables, architecture illustration, charts and appendices; no visible clipping found.
- Checked extracted text bounds: no page overflow. No template placeholders, chart markers, unit-test counts or internal-document referral paths in the report body.
- Verified both retained DOCX template and supplied PDF reference hashes remain unchanged. Detailed checksums are recorded in the final manifest.

## Limits

No new runtime suite, camera/board/field benchmark, deployment, purchase or release sign-off. Preliminary replay measurements do not establish end-to-end inference capacity or event quality. Historical prices are not current quotations. Editable DOCX can paginate differently with another editor or unavailable fonts. Preserved unrelated working-tree changes; no commit or push.
