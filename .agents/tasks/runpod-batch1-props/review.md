# Same-script verified prop alias resolution in the full script parser

Prop facts in `script_full_parser_node.py` used to be checked only against the current shot's own exact source fragment, which meant a model expansion of a shot's short prop name (e.g. 佛珠 → 深棕色小叶紫檀佛珠) was rejected as unsupported even though the detailed form is declared verbatim in the screenplay's own global/character context. This change adds a registry built only from verified context-only blocks, derives short-form aliases structurally (Chinese noun phrases are head-final, so a trailing substring of a verified declaration is a candidate alias — no hardcoded noun list), and wires it into both Phase 1 and Phase 2 prop validation and output canonicalization. It is scoped to `props_list`/`prop_interactions` only; every other fact field is untouched. Three test files add coverage for the alias resolution, first-batch publish, an undeclared prop still blocking, and the unmodified 36-shot/9-batch and sibling-isolation regressions.

Watch for: the commit treats 金链 → 粗金链 only, not the fuller 2厘米宽实心粗金链 quoted in the task — that fuller phrase is declared only in sibling shot_001's body, not in global context, so resolving it would have broken the sibling-isolation guarantee; this is a deliberate, documented trade-off, not an oversight (**confirmed**). The verified-context registry is built from every punctuation-delimited clause of the global context block, not clauses specific to props, so non-prop boilerplate (document title, runtime notes, personality traits) becomes eligible "canonical" text for the alias mechanism (**confirmed**). A prop_interactions value naming two distinct short-form props in one sentence (the fixture's own shot_002 style, "佛珠与金链") is only partially canonicalized — one alias is upgraded, the other is left in short form (**confirmed**).

**Verdict**: APPROVED

## High-level view

The registry-building and alias-matching logic is entirely new, but it plugs into existing, unmodified scaffolding: `batch_context_only` blocks and `is_context` source units already existed to keep global/character setup available to every batch without leaking sibling shot bodies. The new code reuses that boundary rather than inventing a new one, which is why sibling isolation (shot_001's body never counts as evidence for shot_002) holds without extra plumbing.

Validation is strict-first: a prop value is accepted exactly as before if it's literally in the current shot's fragment, and only falls back to the registry when it isn't. Canonicalization runs after validation and only rewrites `props_list`/`prop_interactions`; no other fact field (action, expression, location, dialogue, camera) is touched by the new fallback, which keeps the broader "no hallucination" guarantee for those fields exactly as strict as before.

The registry itself is less precise than "prop declarations": it treats every comma/period-split clause of the entire global/context block as a candidate canonical phrase, regardless of whether that clause is actually about a prop. This doesn't let anything ungrounded through — both the canonical and the derived alias must be literally present in verified text — but it is broader than the stated "prop declarations" scope and will register things like episode runtime notes or personality adjectives as "aliasable" text in other screenplays with different preambles.

A value that names two distinct short-form props in the same sentence — exactly how this screenplay's own "道具互动：佛珠与金链" line reads — only gets one of the two aliases upgraded, because the rewrite function stops at the single best-scoring canonical match instead of chaining all applicable replacements the way the validation function does. The resulting value still passes validation (it's still fully grounded) and still publishes; it's just inconsistently canonicalized.

The feature is correctly wired into the Phase 1 output path that actually reaches the published shot (`shot["props_list"]` is canonicalized and that's the value that ends up in the final merged shot). The equivalent Phase 2 canonicalization of `p2_data["props_list"]` is computed but never read afterward — the merge logic always sources the final `props_list` from Phase 1, a pre-existing asymmetry with `prop_interactions` (which does fall back to Phase 2). That makes the new Phase-2-side `props_list` canonicalization inert code, though harmless since it is simply discarded rather than used incorrectly.

The registry is only populated when the global/context block survives scene-map selection. That happens reliably through the webui/`AnalysisSessionStore` batch flow this task targets, because the session's `batch_context_json` always carries forward blocks marked `batch_context_only`. A direct, session-less call to the node (no `batch_context_json`) goes through the pre-existing `_select_batch_scene_map`, which drops any block that contributes no explicit shot unit — including the global character-bio block — so the new alias resolution silently has nothing to match against in that call path. This fails closed (legitimate aliases just stay rejected, nothing is hallucinated) and the gap is inherited from unmodified code, not introduced by this diff.

<details>
<summary>Issues (4)</summary>

1. **金链 canonicalizes to 粗金链, not 2厘米宽实心粗金链** — the fuller phrase is only in sibling shot_001's body, so resolving it would violate sibling isolation; this is intentional and documented in the commit, but confirm this is the behavior the user actually wants published, since the task text names the fuller phrase explicitly.
2. **Prop registry draws from all context-block prose, not prop-specific clauses** — non-prop boilerplate (titles, runtime notes, personality traits) becomes "aliasable" canonical text for other screenplays. Consider scoping the registry to clauses from character/prop-labeled declarations (e.g. the bio line's prop segment) rather than the entire context-only block.
3. **Compound prop values only partially canonicalized** — `_canonicalize_prop_value` applies only its single best-scoring match, while `_prop_fact_is_supported` chains all applicable alias substitutions. A value naming two distinct short-form props (e.g. "佛珠与金链", which matches this screenplay's own shot_002 phrasing) ends up half-upgraded ("深棕色小叶紫檀佛珠与金链"). Make canonicalization chain replacements the same way validation does, and add a regression case for it.
4. **Phase 2 `props_list` canonicalization is dead code** — `p2_data["props_list"]` is computed but the final merged shot always sources `props_list` from Phase 1 only, never from `p2_data`. Either wire it as a fallback (matching `prop_interactions`) or drop the unused computation.

</details>

<details>
<summary>Details</summary>

### Structural, vocabulary-free alias resolution

`_build_verified_prop_registry` walks `batch_context_only` blocks in full and, for ordinary blocks, only their `is_context`-flagged units — never a scene's aggregated `source_text`, which could contain sibling shot bodies. Each verified clause is split on common CJK/Latin punctuation into candidate canonical phrases. `_prop_alias_for_fragment` then looks for the longest trailing substring (≥2 chars) of a canonical phrase that is itself present, verbatim, in the current shot's own exact fragment — this is the "Chinese is head-final" trick that avoids a hardcoded noun list. `_canonicalize_prop_value` and `_prop_fact_is_supported` both build on this: the former rewrites an accepted value up to its canonical form, the latter accepts a value either directly (old behavior) or after substituting a registered canonical back down to its shot-local alias and re-checking against the exact fragment. Both pieces are instance-level helpers with no reliance on a screenplay-specific vocabulary, so they generalize to any screenplay whose props are declared in a global/character context block and referenced by a trailing substring in a shot.

### Registry scope is broader than "props"

Enumerating the registry built from this fixture's own opening block (title, test-format notes, global visual-style sentence, three character bios) turns up entries like `'180秒'`, `'每个镜头5秒'`, `'性格从容'`, `'3D动画电影质感'` alongside the intended `'粗金链'` and `'深棕色小叶紫檀佛珠'`. Nothing ungrounded is ever accepted this way — both the canonical phrase and the alias must be literally present in verified text — but the mechanism isn't actually scoped to prop declarations, just to "any clause of the context block." A screenplay whose preamble has more boilerplate than this one's would register a correspondingly larger set of non-prop "canonical" phrases, any of which could be coincidentally matched by a model's hallucinated props_list entry that happens to share a trailing substring with one of them and also appears (as that substring) in the shot's own text.

### Partial canonicalization of compound values

```
value = "佛珠与金链"
_prop_fact_is_supported(value, shot_text, registry)   # -> True
_canonicalize_prop_value(value, shot_text, registry)   # -> "深棕色小叶紫檀佛珠与金链"
```
`_prop_fact_is_supported` loops over every registered canonical and substitutes each one found in the value, so a compound value naming multiple props validates correctly as a whole. `_canonicalize_prop_value` instead collects one candidate rewrite per canonical and keeps only the single longest-canonical match, discarding the other applicable substitution. The fixture's own shot_002 uses exactly this compound phrasing for its prop interaction ("道具互动：佛珠与金链"), and no added test exercises `prop_interactions` canonicalization against that line — the new tests cover `props_list` as two separate list items, and the one `prop_interactions` test only exercises a single-prop sentence.

### 36-shot ordering and sibling isolation

The pre-existing 36-shot/9-batch test is unmodified; only two new tests were appended after it, both driven through the real `AnalysisSessionStore`/webui-style context assembly rather than a bespoke scene map, so they exercise the same `batch_context_only`/`is_context` plumbing the production webui batch flow uses. The negative test (`神秘法杖`, undeclared anywhere) confirms the batch still gets rejected by `AnalysisSessionStore.commit_batch`.

</details>

---

<details>
<summary>File map</summary>

- `nodes/director/script_full_parser_node.py` — adds the verified prop registry builder, alias-suffix resolver, and canonicalization/validation helpers; wires them into Phase 1 and Phase 2 prop/prop-interaction validation and into the Phase 2 prompt (registry disclosed as context).
- `tests/test_full_script_batch_regression.py` — adds a batch-1 CPU stub test proving shot_002's two prop aliases canonicalize and the batch commits, and a negative test proving an undeclared prop still blocks commit.
- `tests/test_parser_merge.py` — adds direct unit tests for the registry, alias/canonicalize helpers, sibling-leakage exclusion, an unrelated screenplay's own props, prop-interaction sentence handling, and Phase 1 accept/block via `_phase1_fact_validation_errors`.
- `tests/test_prompt_fidelity.py` — adds a canonical-prop rendering test across both keyframe/video prompts with a sibling-leakage assertion.

Full diff: `git -C e:\MJ\ai_film_editor_nodes diff 991863b...HEAD`

</details>
