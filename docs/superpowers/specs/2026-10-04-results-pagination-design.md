# Results pagination design

## Goal

Make it easier to navigate saved results by showing clickable page numbers alongside previous and next controls.

## Design

Keep the existing `GET /api/documents` request and `loadDocuments(page)` state flow. The Pages footer will use the existing daisyUI `join` group, with Lucide chevron icons for previous/next and numeric buttons for direct page selection. The active page uses `btn-active`; previous and next are disabled at their respective boundaries. When there are at most five pages, show all page numbers. For larger result sets, show a centered window of five consecutive pages, clamped to the first or last page as needed. Add an accessible navigation label and current-page indication.

## Scope and behavior

- Existing filter submission continues to return to page 1.
- Selecting a number or arrow calls `loadDocuments` for that page.
- Keep the current result range label and page size unchanged.
- No API or storage changes.

## Verification

Review the resulting template and page-window calculation. Do not add tests unless requested.
