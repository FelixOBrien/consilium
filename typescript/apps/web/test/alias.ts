import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { plugin } from 'bun';

const root = resolve(import.meta.dirname, '../src/lib');

plugin({
	name: 'web-lib-alias',
	setup(build) {
		build.onResolve({ filter: /^#lib\// }, (args) => {
			const spec = args.path.slice('#lib/'.length).replace(/\.js$/, '');
			const base = resolve(root, spec);
			const candidates = [`${base}.ts`, `${base}.svelte.ts`, base];
			const path = candidates.find((candidate) => existsSync(candidate));
			if (!path) return undefined;
			return { path };
		});
	}
});
