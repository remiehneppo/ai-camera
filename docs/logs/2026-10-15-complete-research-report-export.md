# Complete research report export — 2026-10-15

## Request and scope

User requested a new Design Report covering the complete research directory, with all needed information inside the document rather than referrals to project documents. Existing LibreOffice authorization continues. Kept the previous short report and research sources unchanged.

## Inputs and production

- Read the research report, README, full20-row prices CSV, source registry, outline and fields. Used the retained Design Report DOCX reference and the already available LibreOffice/Python UNO export workflow.
- Reorganized the complete research into executive summary; findings on camera/model/event design/runtime/data/hardware/cost/security and implementation; implications; recommendations and gates; appendix with glossary,20 detailed price observations, criteria, uncertainties and source provenance.
- Included the four BOM scenarios with component costs and assumptions, TCO, storage/bandwidth examples, dataset/license limitations, observed test/replay results and technical alternatives. Clarified B/U/G drain formula, ring budget and accepted-versus-proposed decisions.
- Removed dependencies on other project documents, internal file paths and instructions to open other files. External sources are provenance only; substantive information and qualifications are included inline.
- Cloned the template package; retained page setup, cover image, sections, style system, lists, table formatting, header/footer and updated TOC. Added columns/rows needed by research tables, repeated table headers and reset numbered lists correctly.
- Used isolated headless LibreOffice to update contents, save editable DOCX and export PDF. Temporary production scripts live in /tmp; no dependency was installed.

## Outputs and verification

Directory: `docs/reports/2026-10-15-ai-camera-complete-report/`.

- PDF:41 pages,13 tables,20 price observations,75 external source entries;853241 bytes, SHA256 `713645f826f2228d47e2373e0438338ce0668746f5c9c8b52e45f93088332356`.
- DOCX:6370761 bytes, SHA256 `c9916b37f2345625b3b8cc73f9ab5dec763164c4c22fe4c4bb5bb33c1a90af84`.
- Retained template unchanged: SHA256 `ba1e11258ff52659318a321462a5e598c7bed33cf991329eb91150788fcd1a7b`.
- Included editable content Markdown and build manifest recording input hashes, output sizes/hashes and coverage counts.
- Rendered all pages; inspected contact sheets, tables, multi-page continuations, cover, TOC and appendix. Refined bibliography paragraph grouping, standalone-price pagination and list numbering.
- PDF text checks: no template placeholders or internal-document referrals; all20 price entries and major BOM/storage/test/runtime numbers present. No new benchmark or runtime/board claim.

## Limits

Historical prices/rights/stock/legal and benchmark evidence were not refreshed. No hardware, camera, browser or runtime suite was rerun; no ADR/gate acceptance changed. PDF is the verified sharing version; DOCX pagination may vary with editor/fonts. No commit, push or external hosting publication.
