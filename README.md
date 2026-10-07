# Exploratory Data Analyzer

Upload a CSV or Excel file and explore it in your browser: see what's in each
column, spot missing values, chart distributions, compare columns side by side,
and find correlations — no code required.

![Exploratory Data Analyzer — Overview tab](docs/screenshot.png)

*The Overview tab for a 249-row sports-teams workbook: row counts, a preview of
the data, and a per-column summary of types and missing values.*

## What it does

- **Upload** — CSV, XLSX, or XLS. For Excel workbooks, pick which sheet to
  analyze; if the first row is a title or banner, set the header row to skip it.
- **Smart column handling** — columns that look like IDs (names such as
  `user_id`, `uuid`, or columns where every value is unique) are set aside
  automatically so they don't clutter the analysis. You can pull any of them
  back in with "Force-include".
- **Big files stay fast** — large files are sampled down to a row limit you
  choose (1,000–200,000) so the app stays responsive. You always see both the
  total and analyzed row counts.
- **Forgiving file reading** — for CSVs, the app detects common delimiters and
  encodings automatically, and can skip broken rows in messy files.

Then explore across three tabs:

- **Overview** — row and column counts, a preview of the first 200 rows, and a
  table showing each column's type, missing values, and unique values.
  Downloadable as a CSV.
- **Columns** — pick any column to dig in:
  - **Numbers** — statistics summary and an adjustable histogram.
  - **Text & categories** — most common values with a bar chart, plus text
    length stats.
  - **Dates** — earliest/latest/range, plus a chart of rows over time.
  - **Compare** — optionally pick a second column for a scatter plot, box plot,
    or cross-table.
  - Search, filter by type, and mark favorites for quick access.
- **Correlations** — a heatmap showing which numeric columns move together,
  plus a ranked list for whichever column you pick. Results are cached for
  speed; the app tells you when they're out of date.

## Requirements

The easiest way to run it is **Docker** (nothing else to install). To run it
directly instead, you need **Python 3.11+**.

## Run with Docker

```bash
docker compose up --build -d
```

Then open <http://localhost:8501>. The app only listens on your own machine.

If compose fails with a missing-network error, create it once:

```bash
docker network create website-network
```

## Run without Docker

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/app.py --server.port=8501
```

Then open <http://localhost:8501>.

## Optional: put it on the internet

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
service is included in the compose stack:

1. In the Cloudflare Zero Trust dashboard, create a managed tunnel and copy its
   token into `CLOUDFLARE_TUNNEL_TOKEN` in `.env` (see `.env.example`).
2. Point the tunnel's public hostname at `http://eda-app:8501`.
3. Run `docker compose up -d` — the tunnel starts alongside the app.

If no token is set, the tunnel container simply stays stopped — nothing breaks.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite exercises the real app end to end: file parsing edge cases, ID
detection, the column picker, Excel header rows, and the correlation cache.

## Good to know

- ID detection is a guess based on names and uniqueness — when it guesses
  wrong, use **Force-include** to bring the column back.
- Correlations are cached for speed. If you change the file, sampling, or
  excluded columns, the app asks you to **Re-run correlations** rather than
  silently showing stale numbers.
- Date columns are detected by sampling values, so unusual date formats may
  show up as plain text.
- File uploads are capped at 500 MB.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
