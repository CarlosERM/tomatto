Model: LM Studio local (Qwen3.8 Flash Next)
Date: 2026-11-02
Prompt version: v2 (prompts/p4-test-data.md)
---

{
  "accept": [
    {
      "input": "HTTPS://WWW.Example.COM/Path?Query=1#Fragment",
      "normalized": "www.example.com",
      "note": "Uppercase normalization plus full URL with scheme, path, query, and fragment stripped."
    },
    {
      "input": "http://user:pass@evil.example.com/x",
      "normalized": "evil.example.com",
      "note": "Embedded credentials are stripped; tests open-redirect-style authority parsing."
    },
    {
      "input": "example.com.",
      "normalized": "example.com",
      "note": "Trailing dot is removed and not treated as an empty label; duplicate of EXAMPLE.COM."
    },
    {
      "input": "sub.example.net:8443",
      "normalized": "sub.example.net",
      "note": "Port suffix is stripped from the host."
    },
    {
      "input": "a.b.c.d.example.org",
      "normalized": "a.b.c.d.example.org",
      "note": "Deep subdomain with multiple valid labels is accepted unchanged after lowercasing."
    },
    {
      "input": "café.com.br",
      "normalized": "xn--caf-dma.com.br",
      "note": "Latin-script IDN with precomposed é converts to exact punycode label xn--caf-dma."
    },
    {
      "input": "中国.com",
      "normalized": "xn--fiqs8s.com",
      "note": "CJK IDN converts to exact punycode label xn--fiqs8s."
    },
    {
      "input": "xn--mnchen-3ya.de",
      "normalized": "xn--mnchen-3ya.de",
      "note": "Already-punycode input is accepted as an ASCII hostname without re-encoding errors."
    },
    {
      "input": "192.0.2.1",
      "normalized": "192.0.2.1",
      "note": "IPv4 literal is accepted because only IPv6 literals are rejected."
    },
    {
      "input": "EXAMPLE.COM",
      "normalized": "example.com",
      "note": "Uppercase bare domain normalizes to the same value as example.com., testing duplicate handling."
    },
    {
      "input": "https://shop.example.co.uk/cart?ref=home#top",
      "normalized": "shop.example.co.uk",
      "note": "Full URL with query and fragment on a multi-label public suffix is normalized to the host only."
    },
    {
      "input": "docs.example.edu",
      "normalized": "docs.example.edu",
      "note": "Plain lowercase multi-label hostname passes all validation rules unchanged."
    }
  ],
  "reject": [
    {
      "input": "",
      "note": "Empty string violates the empty-input rejection rule."
    },
    {
      "input": "localhost",
      "note": "Single-label hostname violates the multi-label requirement."
    },
    {
      "input": "bad_host.example.com",
      "note": "Underscore in a label violates the no-underscore rule."
    },
    {
      "input": "exa mple.com",
      "note": "Internal whitespace inside a label violates the no-whitespace rule."
    },
    {
      "input": "-example.com",
      "note": "First label begins with a hyphen, violating the leading-hyphen rule."
    },
    {
      "input": "a..com",
      "note": "Double dot creates an empty label, violating the no-empty-label rule."
    },
    {
      "input": "[2001:db8::1]",
      "note": "Bracketed IPv6 literal violates the IPv6 rejection rule."
    },
    {
      "input": "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijkl.com",
      "note": "First label has 64 characters, exceeding the 63-character label limit."
    }
  ]
}
