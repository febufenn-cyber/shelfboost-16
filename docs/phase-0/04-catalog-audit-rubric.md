# Catalog Audit Rubric

## Purpose

The audit creates a credible diagnosis and prioritization layer. It does not claim that a mechanical score equals SEO performance.

## Sampling plan

For each permissioned catalog, inspect a balanced sample where data permits:

- 20 best sellers;
- 20 recently added products;
- 20 random products;
- 20 poor performers or stale products.

Record selection method and avoid presenting a convenience sample as catalog-wide truth.

## Deterministic checks

### Completeness

- missing title;
- empty description;
- description below an agreed word threshold;
- missing SEO title;
- missing meta description;
- missing image alt text;
- missing category-critical attributes.

### Duplication

- identical normalized titles;
- identical normalized descriptions;
- repeated supplier boilerplate;
- duplicate SEO fields.

### Format and usability

- SEO title or meta description outside practical length ranges;
- malformed or excessive HTML;
- wall-of-text description;
- variant details incorrectly placed at product level;
- unclear capitalization or encoding.

### Risk review

The prototype may flag claim language for human review, but must not declare a claim false without evidence. Examples include cure, clinically proven, guaranteed, 100% safe, certified, sustainable, or material-origin statements.

## Human checks

- are facts internally consistent?
- does the page answer buyer questions?
- is the copy product-specific?
- is the differentiator clear?
- does the structure match the category?
- is any claim unsupported by the supplied source of truth?
- is existing high-performing copy being changed without reason?

## Severity

- **Critical:** missing core identity/content or direct fact conflict
- **High:** likely blocks usefulness or creates major duplication/metadata debt
- **Medium:** meaningful quality or format issue
- **Low:** improvement opportunity with limited immediate risk

## Priority model

Priority should combine:

1. issue severity;
2. business importance, when supplied;
3. confidence in the finding;
4. remediation effort;
5. risk of changing the page.

The Phase 0 prototype implements only evidence-based content checks. Revenue, ranking, traffic, and conversion should not be invented when unavailable.

## Required audit output

- catalog and sample size;
- methods and limitations;
- issue counts by severity;
- top-priority products with exact evidence;
- estimated remediation effort with assumptions;
- fields recommended for draft-only treatment;
- fields excluded from automated generation;
- next pilot proposal.
