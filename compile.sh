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

# Cythonize the solver for C-level performance
cd src
../venv/bin/cythonize -i solver.py sat_instance.py dimacs_parser.py 2>/dev/null || echo "Cython compilation skipped"
cd ..