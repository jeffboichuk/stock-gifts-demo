# Stock gifts: a demo

A dashboard for the ETF shares a person buys the kids in their life on
birthdays and at Christmas, and hands over at 18. This copy runs on four
fictional kids and real prices. It is the one I showed in class, with the
real family swapped out.

Live page: https://jeffboichuk.github.io/stock-gifts-demo/

## The shape

The whole thing is a static site. Nothing runs on a server you own.

| Part | What it is |
| --- | --- |
| `index.html` | The site. One file, about 4,200 lines, HTML, CSS and JavaScript together. No framework and no build step. Open it from disk and it works. |
| `portfolio_data.json` | The data: who the kids are, when their gifts fall, and every share bought. The same records are baked into `index.html` as the `DATA` constant, so the page renders with no fetch. |
| `history.json`, `prices.json` | Daily closes and the latest quote for each ETF. The page fetches these at load and draws the charts from them. |
| `scripts/refresh_prices.py` | Pulls the closes from Yahoo Finance (through the `yfinance` package) and rewrites the two price files. |
| `.github/workflows/refresh-prices.yml` | Runs that script every weekday evening on GitHub's computers and commits the result. The site updates itself without anyone opening it. |
| `sw.js`, `manifest.json`, `icons/` | Make the page installable on a phone as an app. |

Hosting is GitHub Pages: the `main` branch is served as a website. Push, and
the page is live a minute later.

## Why this shape

Three ideas carry over to any site you build, including a store.

1. **Data lives in a file the code reads.** Change a number in
   `portfolio_data.json`, not in the middle of the HTML. When the data has
   a shape, the page can be written once for every kid instead of once per
   kid.
2. **Scheduled jobs belong to the host, not to a laptop.** The prices
   refresh because GitHub runs a script on a timer. A store can do the same
   for inventory counts, exchange rates or a daily report.
3. **Static first.** A page that is only files is free to host, hard to
   break and fast everywhere. Add a server only when the site has to accept
   something from a visitor that must be kept.

## Run it yourself

Fork the repo, then in the fork's Settings, under Pages, set the source to
`main` and `/ (root)`. Your copy is live at
`https://<your-user>.github.io/stock-gifts-demo/`. Edit
`portfolio_data.json` and the `DATA` block in `index.html` to make it yours.

To preview on your own machine, run a file server in the folder:

```bash
python3 -m http.server 8765
```

and open http://localhost:8765/.

To refresh prices by hand:

```bash
pip install yfinance
python3 scripts/refresh_prices.py
```

## Notes for the curious

- Every gift is dated on its occasion (the birthday or Christmas), never on
  the day the shares were bought. Christmas falls on a market holiday, so a
  gift is priced at the last close before it.
- The projection chart on a kid's page compounds today's value to the 18th
  birthday at 4, 8 and 12 percent a year, adding one gift at every future
  occasion.
- The badges are computed from the transactions and the price series,
  except one, which the owner records by hand.
- `CLAUDE.md` holds the notes an AI coding assistant reads before it edits
  the project. The page was built with one; the notes are how it keeps the
  conventions straight between sessions.
