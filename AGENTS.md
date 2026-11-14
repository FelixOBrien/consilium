# Consilium — agent rules

Consilium (working name) is a histopathology case workspace that treats diagnosis support as **information retrieval, not AI diagnosis**: view cases, slides and reports, then find precedent by morphology or text and ask an agent who to consult. It is a hackathon MVP; the submission freeze is **Sun 15 Nov 2026, 12:00 UK**.

Work arrives as Linear issues. Each issue names the docs that specify it. The docs are the source of truth; the issue is the unit of work.

## Read first

1. [docs/index.md](docs/index.md) — how the docs fit together and the ID scheme.
2. [docs/architecture.md](docs/architecture.md) — system design, decisions already made, config.
3. The feature, model and screen docs linked from your issue.

Read [docs/vision.md](docs/vision.md) and [docs/context.md](docs/context.md) once for the why and the constraints.

## Repository map

| Path | What lives there |
| --- | --- |
| `docs/` | Vision, context, architecture, and the feature / story / model / screen specs. |
| `python/` | One `uv` project, package `consilium`: FastAPI API, search, agent, tile server, and the offline ingestion pipeline. |
| `python/sql/migrations/` | Plain SQL migrations. The schema is specified in `docs/models/`. |
| `python/databricks/` | Databricks notebooks, `app.yaml`, and deployment config. |
| `typescript/` | Turborepo (bun). `apps/web` is the SvelteKit app. |
| `data/` | Local slides, features, parquet. **Git-ignored. Never commit.** |

## Hard rules

1. **Not a diagnostic device.** No feature, prompt or UI copy may state a diagnosis for the open case as fact. The product retrieves and summarises precedent, always with citations to cases. Keep the "research prototype, not for clinical use" notice visible.
2. **No data or weights in git.** Slides, embeddings, parquet, thumbnails, model weights and `.env` files stay out of the repository. The repo is public. CONCH-Z is CC-BY-NC-ND, and TCGA slides (GDC open access) and TCGA-Reports (CC BY 4.0) are large and redistributed only by their hosts.
3. **No secrets in code, docs, issues or logs.** Read them from environment variables listed in [docs/architecture.md](docs/architecture.md#configuration).
4. **Code written during the hackathon only.** Do not paste in pre-existing private code. Open-source libraries and pretrained models are fine; add each new one to the list in [README.md](README.md).
5. **Local first.** Everything must run on a laptop against Docker Postgres and local files. Databricks is a deployment target reached through config, never a requirement for development.
6. **Postgres + pgvector is the contract.** Write portable SQL. Lakebase-only features (`lakebase_ann`, `lakebase_bm25`) go behind a setting with a pgvector / `tsvector` fallback.
7. **Two embedding spaces, never mixed.** `conchz` (768-d) holds patches, slides and image-query text. `report` (384-d) holds report chunks and report-query text. Never compare a vector from one with a vector from the other.
8. **Counts come from SQL, not the LLM.** Anything the agent says about how many cases a pathologist reported must come from the `rank_pathologists` tool result.
9. **Synthetic data is labelled.** Pathologists, sign-out dates and case assignments are synthetic. Keep `is_synthetic` flags and do not present them as real.
10. **The API schema is the frontend contract.** Change the Pydantic models, regenerate the TypeScript client, then change the UI. Do not hand-write response types in the web app.

## Working an issue

1. Read the issue and every doc it links. If the docs and the issue disagree, the docs win; say so in the issue.
2. Check `blocked by`. If a blocker is not done, work against the fixture data and the documented contract, or stop and report.
3. Branch `<issue-id>-<short-slug>` from `main`. One issue, one PR.
4. Keep the change inside the issue's scope. Unrelated problems you notice go in a new Linear issue, not in the PR.
5. Run the checks below. Paste the output in the PR.
6. If behaviour differs from a doc, update the doc in the same PR and set its `status`.
7. Put the Linear issue ID in the PR title.

## Checks

```bash
cd python && uv run ruff check . && uv run pytest -q
```

```bash
cd typescript && bun run check-types && bun run lint
```

## Conventions

**Python** — 3.12 for local development (`.python-version`). The package declares `requires-python >= 3.11` and avoids 3.12-only syntax so the same code runs on Databricks Apps. `uv`, `ruff`, type hints everywhere, Pydantic v2 for every API shape, `psycopg` 3 with parameterised SQL (no ORM, no string-built SQL). Routers stay thin; queries live in `consilium/db/` and `consilium/search/`. <!-- pragma: allowlist secret -->

**TypeScript** — SvelteKit with Svelte 5 runes, built as a static SPA. shadcn-svelte components and Tailwind. Server state goes through the generated API client. Create projects and add components with the current CLIs rather than pinning versions from memory.

**SQL** — snake_case, singular table names, text primary keys for domain entities, `created_at timestamptz default now()`.

**Docs** — every doc follows the template in its folder's `index.md`, including front matter.

## Definition of done

- Acceptance checks in the linked feature or screen doc pass, shown by a test or a described manual run.
- Checks above are green.
- Loading, empty and error states exist for any UI touched.
- No new unlisted model, API or dataset.
