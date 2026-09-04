test:
	python -m pytest tests/ -v

# Requires: pip install pyinstaller
build-exe:
	pyinstaller --onefile --name blocklight blocklight/__main__.py

# Output: blocklight.pyz  (chmod +x and rename to 'blocklight' for Linux/Mac)
build-pyz:
	rm -rf _pyz_build
	mkdir _pyz_build
	cp -r blocklight _pyz_build/
	echo "from blocklight.terminal import main; main()" > _pyz_build/__main__.py
	python -m zipapp _pyz_build -o blocklight.pyz -p "/usr/bin/env python3"
	rm -rf _pyz_build
