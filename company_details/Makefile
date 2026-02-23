.PHONY: setup-venv test

setup-venv:
	test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -r company_sim/mock_systems/requirements.txt

test: setup-venv
	.venv/bin/python -m unittest discover -s company_sim/mock_systems/tests -p 'test_*.py' -v
