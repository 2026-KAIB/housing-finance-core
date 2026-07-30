# Loan product snapshot

`loan_base_rows_2026-07-31.json` and `loan_option_rows_2026-07-31.json` are
read-only DBeaver JSON exports from the product database, filtered to products
effective on 2026-07-31.

The exports contain financial-product master data only. They do not contain
customer, account, credential, or transaction data.

The JSON shape is the DBeaver default: one top-level object whose single key is
the executed SQL and whose value is the result-row array. The application
repository unwraps that envelope and validates every row before producing
`ProductCandidate` instances.

This snapshot is a temporary provider while direct PostgreSQL access is
unavailable. The calculation services consume the same `ProductCandidate`
contract, so switching back to `fetch_loan_product_candidates()` does not
require changes to the loan or affordability engines.
