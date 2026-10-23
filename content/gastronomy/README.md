# Gastronomy publishing state

This directory is the durable state for WECARE.DIGITAL Gastronomy publishing.

Current live baseline: **454 published Gastronomy posts** (`progress.json` `live_verified_posts`). The historical Git sequence is verified through GAST-340; the 114 newer live posts must be reconciled to source IDs before assigning the next GAST sequence.

## Production model

- Editorial manifests may contain **1-150 posts**.
- 150 is a maximum production-unit size, not a content target.
- Never invent filler to reach 150.
- Publication happens in AWS-native Blog Studio, not here. The native store refuses a second post under an existing slug.
- Audit runs require **quality_version: 2**.
- Historical v1 manifests remain valid as repository history but cannot pass the v2 audit gate.
- The working branch is **gastronomy-quality**.
- The GitHub workflow validates only; its retired `publish` input fails explicitly.

## Source-specific neutrality and privacy

The quality gate is deliberately **publisher-agnostic**.

Do not hard-code a single source such as Isha into permanent editorial policy.

Each newly supplied PDF, website, cookbook, publisher archive, or source collection must define a private source profile in its manifest:

```json
{
  "quality_version": 2,
  "source_profile": {
    "label": "Internal source label",
    "blocked_public_terms": [
      "Publisher Name",
      "Author Name",
      "Book Title",
      "Institution Name",
      "Private Person Name"
    ],
    "required_public_attribution_terms": []
  }
}
```

`source_profile` is created separately for every new PDF/source. It may include:

- `publisher_names`
- `author_names`
- `publication_titles`
- `institution_names`
- `private_person_names`
- `private_place_names`
- `provenance_phrases`
- additional `blocked_public_terms`
- `allowed_public_terms` for legitimate public culinary terms
- `required_public_attribution_terms` when attribution genuinely must remain

Do not carry one source profile forward blindly to the next PDF.

Normal culinary language is **not** a provenance violation by itself. Phrases such as `cooked with`, `learned from`, `volunteer`, `programme`, family, place, or institution terms should only be blocked when they actually expose the current source's private/provenance context.

`required_public_attribution_terms` is deprecated for public-copy use. New audits must not use attribution exceptions to permit source/reference material in public copy.

The final public article should read as independent WECARE.DIGITAL editorial work. Public copy must not expose source/reference material, named source authors or people, named works, citation/attribution language, source URLs, or source provenance. Internal provenance stays in backend/source-profile metadata only. Genuine culinary or cultural identity may remain when it is part of the subject itself rather than source provenance.

## Generic public-language gate

Public title, slug, SEO, meta description and body are rejected when they contain reconstruction scaffolding such as:

- Source note
- Adapted from
- Independently written from
- The source
- Source recipe
- The cookbook
- In the cookbook
- The book says
- The author / author's
- Learned from
- Cooked with
- Market connection
- Unnecessary source institution or programme language

Possessive personal/source titles such as `Caroline's ...`, `Grandma's ...` or `Aunty ...` are not allowed in public copy when they identify source provenance; generalize the title to the culinary identity.

Health-claim terms in titles/SEO such as `cure`, `detox`, `cleanse`, `heal`, `treat`, `prevent`, or `medicinal` require `health_claim_reviewed: true`.

## Article types

Set `article_type` on new records.

`RECIPE` requires semantic **Ingredients** and **Method** structure.

Non-recipe article types may include:

- `TECHNIQUE`
- `INGREDIENT`
- `CULINARY_ARTICLE`
- `CULINARY_DISTINCTION`
- `MENU_PAIRING`
- `CULINARY_CULTURE_HISTORY`

Non-recipe articles are not forced into artificial Ingredients/Method sections.

## Validation and audit

Validate:

```bash
python scripts/gastronomy_batch.py validate --manifest <v2-manifest>
```

Besides the editorial rules, validation checks each record against the AWS-native blog contract (`scripts/blog_native_contract.py`): a slug the store keeps unchanged, a body under the store's item limit, and only Markdown the post page renders. Recipe structure is read the way the page reads it: `## Ingredients` and `## Method` headings, `- ` ingredient lines, one block per line.

After Blog Studio publishes, audit the live posts:

```bash
python scripts/gastronomy_batch.py audit --manifest <manifest>
```

The audit requires a v2 manifest. It reads each post back through the public read route of `wecare-seo-tools` and checks metadata, recipe structure, source/privacy leakage and formatting corruption.

## Governing rule

**Keep culinary identity. Remove all public source/reference/attribution scaffolding and provenance. Keep source metadata internal only. Never invent WECARE.DIGITAL biography. Preserve recipe facts.**


## Future PDF workflow

For each newly uploaded or linked PDF:

1. Read and inventory the complete relevant source.
2. Create a new source profile for that PDF only.
3. Record publisher, author, publication title, institutions, personal names/places, and provenance phrases privately.
4. Preserve legitimate culinary geography and established food terminology through `allowed_public_terms`.
5. Prepare independent WECARE.DIGITAL articles.
6. Validate a manifest containing **1-150 articles**.
7. Release for publication in Blog Studio only records that pass the public-source-exclusion, privacy, metadata, structure, factual-risk, and safety gates.
8. Audit every published record before treating it as verified.
9. Start a fresh source profile when the next PDF/publisher is supplied.

The quality gate targets public source/reference leakage, privacy/provenance leakage, real content corruption, and relevant factual/safety issues. It does **not** attempt to rewrite ordinary cooking prose simply for stylistic preference.
