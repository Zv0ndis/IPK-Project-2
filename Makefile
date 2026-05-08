.PHONY: all build clean test NixDevShellName

all: build

NixDevShellName:
	@echo "py"

build:
	echo '#!/usr/bin/env bash' > ipk-rdt
	echo 'python3 "$$(dirname "$$0")/src/main.py" "$$@"' >> ipk-rdt
	chmod +x ipk-rdt
	
clean:
	rm -f ipk-rdt

test:
	python3 test_suite.py
