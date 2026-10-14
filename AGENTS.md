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
- Every UI statistic/chart must use the same filtered records as the table.
- Institutional submissions and public REIT market/fund data are separate
  populations. Do not combine their amounts or statuses.
- Preserve MIT attribution to the upstream tingdall/reits-dashboard project.
- The repository is private. Do not enable a public web deployment without an
  explicit user instruction to publish the website.
