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

## Transcript → test mapping

| Prompt | Transcript here | Curated into |
|--------|-----------------|--------------|
| P1 contract | `p1-v?-*.md` | `tests/integration/test_p1_contract.py` |
| P2 scenarios | `p2-v?-*.md` | `tests/integration/test_p2_scenarios.py` |
| P3 negative | `p3-v?-*.md` | `tests/integration/test_p3_negative.py` |
| P4 test data | `p4-v?-*.md` | `tests/integration/data/blocklist_dataset.json` + `test_p4_test_data.py` |
