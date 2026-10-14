# Offline regression fixtures

The two page fixtures preserve one public institutional REIT record from each exchange response captured on 2026-10-14. Report metadata is reduced to pagination fields, and record counts are set to one so these are self-contained pages.

They intentionally preserve the Shenzhen HTML `a-param` project detail attribute, whose official project ID cannot be read from the `javascript:` href. No credentials or private-account data are included.

Pagination and duplicate cases are constructed in tests so the suite can exercise more than 200 SSE records, more than 100 SZSE records, multi-keyword overlap, and interrupted refreshes without network access.
