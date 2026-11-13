# Documentation site

`docs.myastroboard.org` is built from `docs/*.md` with [mdBook](https://rust-lang.github.io/mdBook/)
by the [Documentation site](../.github/workflows/docs-site.yml) workflow, and published to GitHub
Pages on every push to `main` that touches the docs. The Markdown files stay written for GitHub:
nothing in `docs/` is specific to the site.

| File | Role |
|---|---|
| `book.toml` | mdBook settings (title, themes, search, edit link) |
| `SUMMARY.md` | The site menu. **A page missing here is not published**: add every new `docs/*.md` page to it, under the same audience as in `docs/README.md` |
| `landing.html` | Top of the home page (hero, "I want to..." cards, screenshots); `docs/README.md` follows it |
| `404.md` | The "page not found" page |
| `theme/head.hbs` | Link preview tags, and the bundled icons, KaTeX, stylesheet and scripts |
| `theme/site.css` | The myastroboard.org palette on the mdBook "navy" (dark) and "light" themes, home page components |
| `theme/site.js` | "Live demo" link in the top bar, zoom on screenshots |
| `theme/math.js` | Formula rendering |
| [`scripts/build_docs_site.py`](../scripts/build_docs_site.py) | Assembles the book, builds it, checks the result |

The build script turns links that leave `docs/` into GitHub URLs, protects `$...$` / `$$...$$`
formulas from Markdown, bundles KaTeX at a pinned version (checked against its npm integrity hash),
replaces images hosted elsewhere (badges) by their text, converts the screenshots to WebP, adds a
"Last updated" line from each page's last commit, writes `sitemap.xml` and `robots.txt`, and fails on
a dead link, a missing anchor, or any asset loaded from another host. It needs Pillow
(`requirements.txt`) and the git history.

## Preview locally

```bash
# mdBook: download the binary for your system from
# https://github.com/rust-lang/mdBook/releases (same version as MDBOOK_VERSION in the workflow)
python scripts/build_docs_site.py --mdbook path/to/mdbook
python -m http.server 8099 --directory docs-site/build/site
```

Then open http://127.0.0.1:8099. The output in `docs-site/build/` is not committed.

## One-time setup (maintainer)

1. Repository **Settings -> Pages -> Build and deployment -> Source**: *GitHub Actions*.
2. Same page, **Custom domain**: `docs.myastroboard.org`, then **Enforce HTTPS** once the
   certificate is issued.
3. DNS (Cloudflare): a `CNAME` record `docs` -> `myastroboard.github.io`, **DNS only** (grey cloud),
   so that GitHub can issue the HTTPS certificate.
