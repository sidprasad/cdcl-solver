#!/bin/bash

########################################
############# CSCI 2951-O ##############
########################################

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
# Ensure venv has an up-to-date pip, setuptools and wheel, then install requirements
./venv/bin/python -m pip install --upgrade pip setuptools wheel
./venv/bin/pip install -r requirements.txt

# Clean old build artifacts so we always get a fresh compile
rm -f src/*.so src/solver.c src/sat_instance.c src/dimacs_parser.c
rm -rf src/build

# Compile everything to C via Cython, then compile the C with:
#   -O3              maximum optimisation
#   -march=native    target this exact CPU
#   -finline-functions / -funroll-loops
#   -ffast-math      aggressive FP
#   -flto            link-time optimisation (inline across .c files)
#   + all Cython safety checks OFF (boundscheck, wraparound, nonecheck, …)
#
# See src/setup.py for the full flag list and directive config.
cd src
../venv/bin/python setup.py build_ext --inplace 2>&1
# Clean up distutils build dir (the .so files are already in src/)
rm -rf build
cd ..