#!/bin/bash

########################################
############# CSCI 2951-O ##############
########################################

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Install requirements into the virtual environment
./venv/bin/pip install -r requirements.txt

# Clean old build artifacts so we always get a fresh compile
rm -f src/*.so src/solver.c src/sat_instance.c src/dimacs_parser.c

# Cythonize the solver for C-level performance
cd src
../venv/bin/cythonize -i solver.py sat_instance.py dimacs_parser.py 2>/dev/null || echo "Cython compilation skipped"
cd ..