-- Vector and keyword indexes. Run after rows are loaded (docs/models/patch.md rule 5).
-- SEARCH_BACKEND=pgvector uses the statements below.
--
-- SEARCH_BACKEND=lakebase is not implemented in this migration.
-- Do not create lakebase_ann or lakebase_bm25 here (architecture D5).
-- Lakebase on this project stays on these same pgvector HNSW and GIN indexes
-- (docs/context.md). The Python runner refuses SEARCH_BACKEND=lakebase
-- rather than emitting Lakebase Search syntax.

create index slide_embedding_hnsw
    on slide using hnsw (embedding halfvec_cosine_ops)
    where status = 'ready';

create index patch_embedding_hnsw
    on patch using hnsw (embedding halfvec_cosine_ops)
    where in_corpus;

create index report_chunk_embedding_hnsw
    on report_chunk using hnsw (embedding vector_cosine_ops)
    where in_corpus;

create index report_search_tsv_gin
    on report using gin (search_tsv);
