# Consilium web

The Consilium frontend is a SvelteKit static SPA inside the repository's Bun and Turborepo workspace.

## Development

From `typescript/`:

```sh
bun install
bun run dev --filter web
```

## Checks

From `typescript/`:

```sh
bun run check-types
bun run lint
```

## Build

From `typescript/apps/web/`:

```sh
bun run build
```

The static adapter writes deployable output to `build/`.
