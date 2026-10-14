# REITs research dashboard

Static HTML/CSS/JS plus Python standard-library collectors. Run locally with
`python3 -m http.server 8765`, then open the printed localhost URL.

- Collect with `python3 -m collectors.institutional`; never replace complete
  data after an incomplete source/keyword/page fetch.
- Run `python3 -m unittest discover -s tests -v`,
  `node --check assets/app.js`, and
  `python3 scripts/validate_data.py data/institutional.json` before committing.
- Project identity is `(exchange, official project ID)`, never the row number.
- Preserve exact official project detail links and keyword provenance.
- Keep unknown asset classifications unknown; preserve repository overrides.
- Keep the two-level classification taxonomy consistent in filters, charts,
  detail views, local overrides and CSV exports. Normalize legacy labels
  仓储物流 to 物流仓储 and 办公楼 to 办公 without losing browser-local marks.
- Every UI statistic/chart must use the same filtered records as the table.
- Institutional submissions and public REIT market/fund data are separate
  populations. Do not combine their amounts or statuses.
- Preserve required copyright and license notices in LICENSE.
- Describe the project as direct collection of institutional REIT submissions
  from the Shanghai and Shenzhen exchanges. Document actual source queries,
  definitions, coverage, and quality checks.
- Keep the source repository private. Publish the static dashboard through
  GitHub Pages under the user's website deployment instruction.
