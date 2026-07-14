.PHONY: test phase0-test phase0-audit-sample phase1-test phase1-demo phase2-test phase2-demo phase3-test phase4-test phase5-test phase6-test phase7-test phase8-test

test: phase0-test phase1-test phase2-test phase3-test phase4-test phase5-test phase6-test phase7-test phase8-test

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

phase4-test:
	PYTHONPATH=phase4 python3 -m unittest discover -s phase4/tests -v

phase5-test:
	PYTHONPATH=phase4:phase5 python3 -m unittest discover -s phase5/tests -v

phase6-test:
	PYTHONPATH=phase4:phase6 python3 -m unittest discover -s phase6/tests -v

phase7-test:
	PYTHONPATH=phase4:phase7 python3 -m unittest discover -s phase7/tests -v

phase8-test:
	PYTHONPATH=phase4:phase8 python3 -m unittest discover -s phase8/tests -v
