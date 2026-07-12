.PHONY: test audit-sample

test:
	python3 -m unittest discover -s prototypes/catalog-audit/tests -v

audit-sample:
	python3 prototypes/catalog-audit/audit_catalog.py prototypes/catalog-audit/sample/shopify-products.csv --output-dir .audit-output
