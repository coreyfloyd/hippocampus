# Release candidate review

## Scope

`0.8.1` retires Firecrawl from the research skills. Web search moves to the runtime's built-in `WebSearch` tool, and page extraction moves to Defuddle's hosted endpoint at `https://defuddle.md/`.

## Compatibility

No installer, profile, or package-path change. This release is skill content and the optional-integration clause of the Karpathy wiki contract only, so a valid v0.8.0 installation upgrades in place with no migration.

The removed integration was optional and runtime-detected, so an installation that never had Firecrawl configured behaves identically before and after. Installations that did have it lose nothing the skills still call: `firecrawl_search_feedback` refunded a Firecrawl credit and has no counterpart, and no skill referenced `firecrawl_crawl`, `_map`, `_monitor`, `_agent`, `_parse`, `_interact`, or `_download`.

Defuddle's hosted endpoint needs no install, no API key, and no local Node runtime. `WebSearch` is provided by the runtime. Neither adds a prerequisite to the installer.

The signing key material and fingerprint are unchanged.

## Verification

- `bash tests/test-contracts.sh`
- `bash tests/test-install.sh`
- `bash tests/test-release.sh`
- `swift test` in `skills/transcribe/tools/apple-speech`
- `git diff --check`

## Release-note draft

`v0.8.1` replaces Firecrawl with the runtime's built-in `WebSearch` tool and Defuddle's hosted extraction endpoint across the research skills.

Search calls now pass `allowed_domains` where they previously used `includeDomains` or a `site:` prefix. Page extraction is `curl https://defuddle.md/<url>`, which returns Markdown with YAML frontmatter and requires no install, API key, or local Node. The `firecrawl_search_feedback` credit-refund calls are removed.

Reddit handling is unchanged. Reddit blocks Defuddle exactly as it blocked Firecrawl, so the signed-in-browser route and the snippet-level fallback stand as written.

Updated: `research-quick`, `research-feedback`, `research-dev`, `research-feature`, `research-topic`, `research-sources`, and the optional-integrations clause of `contracts/karpathy-wiki.md`.

## Publication checklist

- [ ] Complete the verification commands above from the candidate commit.
- [ ] Tag the exact pushed commit as `v0.8.1`.
- [ ] Maintainer signs the candidate using `HIPPOCAMPUS_GPG_KEY`.
- [ ] Verify the signed archive and published release assets before announcing.
