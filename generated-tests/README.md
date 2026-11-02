# generated-tests/ — raw LLM transcripts (evidence)

This folder holds the **verbatim** responses from running each prompt in `prompts/` against a real LLM, exactly as required by the Unidade III exercise ("experimente esses prompts com uma LLM e registre os casos de teste gerados").

## Workflow

1. Open one file from `prompts/`, copy the fenced **v2** block (and optionally v1 for comparison).
2. Paste it into your chatbot of choice (for P1, first run `uv run python scripts/export_openapi.py` and paste `docs/openapi.yaml` where indicated).
3. Save the raw response here — no editing, no curation. Curation happens afterwards, when transcripts are translated into executable tests under `tests/integration/`.

## Naming convention

```
p<n>-v<k>-<model>-<yyyymmdd>.md
example: p2-v2-chatgpt-4o-20261101.md
```

Start each transcript file with a metadata header, then the raw output:

```markdown
Model: ChatGPT (GPT-4o)
Date: 2026-11-01
Prompt version: v2 (prompts/p2-scenarios.md)
---
<raw response pasted verbatim>
```

## Transcripts on file

All runs: **Qwen3.8 Flash Next** served locally by LM Studio, each in a fresh agent context with no access to this repository (the P1 runs were additionally allowed to read only `docs/openapi.yaml`, which is the spec they are supposed to be given). Date: 2026-11-02.

| Run | Transcript | Verdict |
|-----|-----------|---------|
| P1 v1 | `p1-v1-qwen3.8-flash-next-20261102.md` | Runnable pytest + `jsonschema`, all endpoints, no invented ones; silent on stale-version/409, and `pytest.skip` would mask an unreachable Sync API |
| P1 v2 | `p1-v2-qwen3.8-flash-next-20261102.md` | 19-row checklist incl. all four cross-service promises; exposed a contradiction inside my own prompt (rule 3 vs rule 4) and asserted an undocumented `409` |
| P2 v1 | `p2-v1-qwen3.8-flash-next-20261102.md` | ~30 scenarios, broad but unanchored: invented auth, expiring blocks, delta sync, pagination, wildcards; never named the real mechanisms |
| P2 v2 | `p2-v2-qwen3.8-flash-next-20261102.md` | 7 both-service scenarios with named seams, zero invention; S7 anticipated the stale-ETag bug we later hit for real |
| P3 v1 | `p3-v1-qwen3.8-flash-next-20261102.md` | ~50 generic hardening cases (JWT, gzip bomb, IDOR); cross-service contract absent; only *advises* end-to-end testing |
| P3 v2 | `p3-v2-qwen3.8-flash-next-20261102.md` | 14 concrete outage/injection rows with user-visible symptoms; slipped on the payload key (`domains` vs `sites`) |
| P4 v1 | `p4-v1-qwen3.8-flash-next-20261102.md` | The predicted failure: 20 brand names, no edge inputs at all |
| P4 v2 | `p4-v2-qwen3.8-flash-next-20261102.md` | Exact row counts, punycode verified against Python's `idna`, duplicate-normalization pair present |

## Transcript → test mapping

| Prompt | Transcript here | Curated into |
|--------|-----------------|--------------|
| P1 contract | `p1-v?-*.md` | `tests/integration/test_p1_contract.py` |
| P2 scenarios | `p2-v?-*.md` | `tests/integration/test_p2_scenarios.py` |
| P3 negative | `p3-v?-*.md` | `tests/integration/test_p3_negative.py` |
| P4 test data | `p4-v?-*.md` | `tests/integration/data/blocklist_dataset.json` + `test_p4_test_data.py` |
