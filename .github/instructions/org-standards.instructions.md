---
applyTo: "**"
---

# MyAstroBoard organization standards

The rules every repository of the [MyAstroBoard organization](https://github.com/myastroboard)
follows, for humans and AI assistants alike.

**This file is synced.** Its source of truth is `standards/ORG_STANDARDS.md` in
[myastroboard/.github](https://github.com/myastroboard/.github); each repository receives a copy at
`.github/instructions/org-standards.instructions.md` through an automated pull request. Do not edit
the copy: change the source, and every repository follows.

## How the rules are layered

1. **This file** - what is true in every repository.
2. **The repository's own AI file** (`CLAUDE.md` or `AGENTS.md`) - what the project is, its
   layout, its exact commands, and the rules only it has. It imports this file
   (`@.github/instructions/org-standards.instructions.md`) instead of restating it.
3. **The repository's `CONTRIBUTING.md`** - local setup and tooling for human contributors. It
   links to the organization's
   [CONTRIBUTING.md](https://github.com/myastroboard/.github/blob/main/CONTRIBUTING.md) for
   everything general.

A repository may add stricter rules. It may only relax one of the rules below by saying so
explicitly in its own AI file, with the reason (example: a static website has no backend logging).
The non-negotiables in section 1 are never relaxed.

---

## 1. Non-negotiables

- **AI assistants never run `git commit`**, and never offer or ask to commit. The maintainer does
  every commit. Proposing a commit message, staging, or showing a diff on request is fine.
- **Never push, force-push, rebase shared branches, or rewrite published history** without an
  explicit request.
- **Disclose AI assistance.** When an AI tool wrote a meaningful part of a change, its commit
  carries a `Co-Authored-By:` trailer naming the tool (for example
  `Co-Authored-By: Claude <noreply@anthropic.com>`), and the pull request description says so.
  Commit messages an assistant proposes include that trailer. For privacy, never link to the
  assistant session itself.
- **Never skip or disable hooks, signing, or CI checks.** If a check fails, fix the cause.
- **Report outcomes honestly.** If tests fail, say so and show the output. Say which commands were
  actually run.
- **The maintainer is pseudonymous.** Their real name never appears in any repository - docs,
  comments, commit messages, examples. Write "the maintainer"; pronouns they/them.
- **No secrets in the repository**: no tokens, keys, passwords or personal data in code, fixtures,
  examples, or committed `.env` files. `.env.example` holds placeholders only.

## 2. Before writing code

- Read the repository's AI file, its `CONTRIBUTING.md`, and the `docs/` page for the subsystem you
  are about to touch.
- Match the surrounding code: naming, idioms, comment density, file layout, error handling.
- Prefer editing existing files over adding new ones. Do not introduce a new framework,
  dependency, or architectural pattern to solve a local problem.
- Do not add work outside the scope you were asked for. Note it as a follow-up instead.

## 3. Language and text

- **English** for all code, identifiers, comments, docstrings, logs, API error messages, docs,
  commit messages, and pull request text.
- **User-facing UI text goes through i18n**, never hardcoded in any language. `en` is the reference
  language; every other language file carries the same keys, value types, and placeholder names,
  and a check in CI enforces that parity.
- **ASCII punctuation only** in every source and translation file, French included: straight
  apostrophe `'` (U+0027), never the curly U+2019; hyphen-minus `-` (U+002D), never an en or em
  dash. Both look like their ASCII counterpart and break searches, diffs and tests.

## 4. Logging and output

- Each backend has **one centralized logger factory**; use it (`logger = get_logger(__name__)`).
  The repository's AI file names the import path.
- **Never** use `print()` or `console.log` for diagnostics in committed code.
- **Never** import the raw `logging` module or configure your own handlers.
- Pick the right level (DEBUG tracing, INFO normal flow, WARNING unexpected but handled, ERROR
  failure, CRITICAL cannot continue) and include context: inputs, ids, paths.
- **Never log** passwords, tokens, secrets, push keys, precise coordinates, or free-text user
  content. Usernames and IP addresses are acceptable when logs have a retention limit.

## 5. Frontend

- **No HTML string sinks**: no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, or
  `dangerouslySetInnerHTML`. Build the DOM with explicit APIs or the framework's components; put
  API- or user-derived text in `textContent`.
- **No static inline styles** (`style="..."`, `element.style.x = ...`) for colors, sizes, spacing or
  fonts: use a CSS class, even a small one-off. Allowed exceptions: runtime show/hide, and genuinely
  per-instance dynamic values (a progress-bar width, an offset computed from data).
- **Every theme, always.** When a project ships light and dark themes, style through its semantic
  tokens, never a theme-specific hardcoded color, and check new surfaces in both.
- **Mobile-first**: check every new layout at phone width.
- **No third-party assets at runtime**: no CDN-hosted scripts, fonts or images, no analytics, no
  tracking pixels. Vendor what you need.

## 6. Architecture

- One class or responsibility per file where practical; keep data loading, business logic and
  presentation apart.
- **No new import cycle between feature packages.** A helper needed by two features moves to a
  shared `utils` module. A request-time call that would close a cycle uses a lazy import inside the
  function, with a one-line comment saying why.
- Routes may import services; services never import routes.

## 7. Data correctness and security

- **Validate all external and user input** before saving it, using it in a file path, or returning
  it in a response. Use the repository's existing validators; do not roll your own.
- **No silently staling data**: no hardcoded, time-stamped data that quietly goes empty or wrong.
  Prefer a live or auto-refreshed source; when a static fallback is unavoidable, document where it
  comes from and when it expires.
- **Never invent a value.** A number shown to a user is traced to a real computation or dataset;
  an estimate is labeled as one.
- Pin dependencies, keep Dependabot enabled, and check a new dependency's license: every
  repository is **AGPL-3.0**, so the dependency must be compatible.
- Docker images must keep running on x86-64 CPUs without x86-64-v2 (Proxmox `kvm64`, the Home
  Assistant OS VM default). Repositories that publish an image run the `cpu-compat` check.

## 8. Personal data (GDPR)

Our applications are self-hosted: each operator is the data controller, and the application must
make compliance easy for them. When a repository stores or sends personal data, it keeps a
`docs/PRIVACY.md` inventory, and every feature follows these rules:

- **Erasure and export cover everything.** Deleting an account deletes all of its data; the
  personal data export includes all of it. A new kind of per-user data is wired into both in the
  same change.
- **Strip image metadata** (EXIF: GPS position of the observer's home, camera serial numbers)
  before writing any user upload.
- **Private by default.** Anything that exposes one user's data to others is off until turned on.
  A new default that shares more applies to new installs only.
- **Third parties are documented.** A new outbound call carrying coordinates, an IP address, or
  user content gets a row in PRIVACY.md, with the country when outside the EU.
- **Secrets are never exported** or returned by an API: password hashes, TOTP secrets, push keys.
- A new field, store or integration holding personal data updates PRIVACY.md in the same change.

## 9. Refactoring safety

- After renaming anything that crosses files (function, parameter, dict key, config key, route,
  translation key), **grep the whole repository**, tests and mocks included, for the old name
  before calling it done. Broad `except` blocks hide the callers you missed.
- After a large mechanical change, run the full test suite, not just the touched files.
- In indentation-delimited files, confirm where a class or function really ends before inserting
  after it.

## 10. Tests

- Tests mirror the source layout (`pkg/foo.py` -> `tests/pkg/test_foo.py`). No catch-all
  "coverage boost" files spanning unrelated modules.
- Descriptive names, and a docstring stating the behavior under test.
- **Never cite source line numbers or coverage branch numbers** in test docstrings or comments;
  describe the behavior instead.
- Cover the success path, the failure path, and edge cases. Mock external dependencies: network,
  clock, containers, third-party APIs.
- New behavior ships with tests that prove it. **Never loosen a tolerance or an assertion to make
  a test pass**: fix the code, or flag the problem.

## 11. Git workflow

- `main` is always releasable. Work happens on a branch named `<type>/<short-description>`:
  `feature/`, `fix/`, `chore/`, `docs/`, `refactor/`, `test/`, `ci/`.
- **Conventional commits**, imperative mood, subject at most 72 characters:

  ```
  <type>(<optional scope>): <subject>

  <body: what and why>

  <footer: Fixes #123>
  ```

  Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `ci`, `chore`.
- Pull requests are squash-merged; the pull request title follows the same format.

## 12. Changelog

Every repository that ships releases keeps a `CHANGELOG.md`:

- New entries go under `## [Unreleased]`, in `### Features`, `### Fixes`, or `### Breaking changes`
  (replace the `- None.` placeholder). Released sections are `## X.Y.Z (YYYY-MM-DD)`.
- **A pull request from a `feature/` or `fix/` branch must add an entry**; CI fails it otherwise.
  Other branch types may add one when the change is user-visible.
- **One or two lines per entry**: what changed and where to find it. Detail goes in `docs/`, linked
  from the entry. The release notes are generated from this section.
- On release, an automated pull request moves `[Unreleased]` into the new version section.

## 13. Python tooling

- **ruff** formats and lints. Each repository's `ruff.toml` extends the shared baseline
  (`extend = ".github/org/ruff.base.toml"`) and may add rules with `extend-select` (never `select`,
  which replaces the baseline) or override the line length; it does not `ignore` a baseline rule
  without a comment saying why.
- Type checking with **pyright** or **mypy**, as each repository has chosen; its AI file names the
  exact command and scope.
- Tests with **pytest**.

## 14. Definition of done

Do not report a change as complete until all of these hold. The repository's AI file lists the
exact commands.

- [ ] Tests pass (backend and frontend)
- [ ] Formatter produces no diff, linter and type checker report nothing
- [ ] i18n parity check passes if UI text changed
- [ ] Contract or route inventory tests updated if a route or public API changed
- [ ] `CHANGELOG.md` entry added (`feature/` and `fix/` branches)
- [ ] Docs updated for any user-facing or behavioral change
- [ ] English text and ASCII punctuation only
- [ ] No `print()` or raw logging, no HTML string sinks, no new static inline styles
- [ ] Personal data rules followed, and PRIVACY.md updated if relevant

---

## 15. The MyAstroBoard family

| Repository | What it is | Local ports |
|---|---|---|
| [myastroboard](https://github.com/myastroboard/myastroboard) | Self-hosted astronomy dashboard (Flask) | 5000 |
| [myastroshine](https://github.com/myastroboard/myastroshine) | Astrophoto processing (FastAPI + React) | 8002 API, 3000 Vite |
| [myastroshot](https://github.com/myastroboard/myastroshot) | Raspberry Pi night camera (FastAPI + React PWA) | 8001 API, 5174 Vite |
| [myastrocast](https://github.com/myastroboard/myastrocast) | Upcoming-event visuals for creators (FastAPI + React) | 8000 API, 5173 Vite |
| [lovelace-myastroboard-card](https://github.com/myastroboard/lovelace-myastroboard-card) | Home Assistant Lovelace card | - |
| [home-assistant-apps](https://github.com/myastroboard/home-assistant-apps) | Home Assistant apps wrapping the Docker Hub images | - |
| [website](https://github.com/myastroboard/website) | Static showcase website | - |

- **Ports are shared across the family**: never reuse one listed here for another project, and
  add new projects to this table.
- **Scope boundaries**: real-time "should I go out tonight" planning belongs to MyAstroBoard;
  days-to-weeks-ahead event content to MyAstroCast; image processing to MyAstroShine; capture to
  MyAstroShot. A feature that belongs to a sibling goes there, or integrates with it.

### Cross-repository contracts

| Contract | Producer | Consumer(s) |
|---|---|---|
| MQTT / Home Assistant entities | myastroboard | lovelace-myastroboard-card |
| AstroDex photo round-trip | myastroboard, myastroshine | each other |
| Docker Hub images and versions | myastroboard, myastroshine | home-assistant-apps |

A change to a contract names the consumer repositories in its pull request and changelog entry,
stays backward-compatible for at least one release, or is listed under `### Breaking changes`.
