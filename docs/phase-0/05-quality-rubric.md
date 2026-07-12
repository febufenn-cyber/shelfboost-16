# Draft Quality Rubric

Quality is evaluated field by field. Factual integrity and claim safety are hard gates and cannot be offset by attractive style.

## Scored dimensions

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Factual integrity | Invents or contradicts facts | Mostly accurate but ambiguous | Every material statement traceable to approved input |
| Claim safety | Unsupported or regulated claim | Some wording requires review | No unsupported claim; uncertainty is surfaced |
| Brand alignment | Clearly wrong voice | Generic but acceptable | Matches approved vocabulary, tone, and exclusions |
| Product specificity | Could describe anything | Uses some product details | Clearly belongs to this exact product |
| Buyer usefulness | Omits key decision information | Covers basic benefits | Answers major buyer questions without fluff |
| SEO usefulness | Stuffed or irrelevant | Basic natural relevance | Clear intent alignment without sacrificing readability |
| Readability | Confusing or poorly structured | Understandable | Scannable, concise, and category-appropriate |
| Format safety | Breaks required format | Minor cleanup needed | Valid, preserved, and ready for controlled review |

## Hard gates

A draft is rejected before merchant review when:

- factual integrity is below 5;
- claim safety is below 5;
- product identity is ambiguous;
- required source facts are missing;
- HTML or field mapping is unsafe.

## Merchant outcome codes

- `accepted_unchanged`
- `accepted_light_edit` — wording or formatting only; core draft retained
- `accepted_heavy_edit` — substantial rewrite
- `rejected_fact`
- `rejected_claim`
- `rejected_brand`
- `rejected_generic`
- `rejected_seo`
- `rejected_format`
- `deferred_missing_source`

## Phase 0 target

Across at least three pilots:

- 60% or more accepted unchanged or with light edits;
- zero known serious unsupported claims delivered;
- all factual issues recorded and traced to source, prompt, model, or review failure;
- review time compared with the participant's prior workflow.
