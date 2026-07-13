.PHONY: test phase0-test phase0-audit-sample phase1-test phase1-demo phase2-test phase2-demo phase3-test

test: phase0-test phase1-test phase2-test phase3-test

phase0-test:
	python3 -m unittest discover -s prototypes/catalog-audit/tests -v

phase0-audit-sample:
	python3 prototypes/catalog-audit/audit_catalog.py prototypes/catalog-audit/sample/shopify-products.csv --output-dir .audit-output

phase1-test:
	PYTHONPATH=phase1 python3 -m unittest discover -s phase1/tests -v

phase1-demo:
	./phase1/run-demo.sh /tmp/shelfboost-phase1-demo

phase2-test:
	PYTHONPATH=phase1:phase2 python3 -m unittest discover -s phase2/tests -v

phase2-demo:
	./phase2/run-demo.sh /tmp/shelfboost-phase2-demo

phase3-test:
	PYTHONPATH=phase1:phase2:phase3 python3 -m unittest discover -s phase3/tests -v
