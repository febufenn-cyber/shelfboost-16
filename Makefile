.PHONY: test phase0-test phase0-audit-sample phase1-test phase1-demo

test: phase0-test phase1-test

phase0-test:
	python3 -m unittest discover -s prototypes/catalog-audit/tests -v

phase0-audit-sample:
	python3 prototypes/catalog-audit/audit_catalog.py prototypes/catalog-audit/sample/shopify-products.csv --output-dir .audit-output

phase1-test:
	PYTHONPATH=phase1 python3 -m unittest discover -s phase1/tests -v

phase1-demo:
	./phase1/run-demo.sh /tmp/shelfboost-phase1-demo
