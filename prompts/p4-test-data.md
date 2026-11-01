# P4 — Prompt de Dados de Teste (Test-data prompt)

**Intenção (PT-BR):** gerar um dataset realista e adversarial de domínios para popular os testes
parametrizados — IDN/punycode, URLs completas, credenciais embutidas, portas, rótulos inválidos.
Alimenta `tests/integration/data/blocklist_dataset.json` e `test_p4_test_data.py`.

---

## v1 (original)

```text
Generate a list of 20 realistic website domains I can use as test data for testing a website-blocking API.
```

**Observed result:** 20 boring names (`facebook.com`, `youtube.com`...). Zero edge value — none of it would ever catch a normalization bug, and half were duplicates modulo case.

## v2 (refined — use this one)

**What changed and why:** switched from "domains" to *inputs users actually paste* (URLs with credentials, ports, trailing dots), demanded machine-readable JSON with the expected normalized form per row (this is what makes the output directly executable as a parametrized test), and enumerated the exact edge families so diversity is guaranteed rather than hoped for.

```text
You are a test-data engineer for a domain-blocking API. Input format accepted by the API: any string a user might paste — bare domains, full URLs (with scheme/path/query/fragment), uppercase text, hosts with ports or trailing dots, internationalized domains, and hostile inputs like embedded credentials ("http://user:pass@evil.example.com/x").

Rules of the system under test: it normalizes input to a lowercase multi-label ASCII hostname (unicode → punycode), strips scheme/path/query/fragment/port/credentials/trailing-dot, and REJECTS with 422: empty strings, single labels ("localhost"), underscores in labels, internal whitespace, leading-hyphen labels, empty labels ("a..com"), IPv6 literals, labels over 63 chars.

Produce ONLY a JSON object (no prose):
{
  "accept": [ {"input": "...", "normalized": "<exact expected ASCII hostname>", "note": "<why this is interesting>"} ],
  "reject": [ {"input": "...", "note": "<which rule it violates>"} ]
}

Requirements:
1. Exactly 12 accept rows and 8 reject rows.
2. Accept rows MUST collectively include: uppercase normalization, full URL with query+fragment, embedded credentials (open-redirect style), trailing dot, port suffix, deep subdomain, Latin-script IDN (e.g., accented .com.br), CJK IDN, already-punycode input, IP literal, and two inputs that normalize to the SAME domain as another row (to test duplicate handling).
3. Compute "normalized" precisely — punycode must be correct, not approximate.
4. Reject rows: one per rejection rule listed above.
```

**Transcript:** save your raw LLM response as `generated-tests/p4-v2-<model>-<date>.md`. Note: the two same-normalization inputs are intentional — the suite asserts the second is a legitimate 409 (normalization equivalence).
