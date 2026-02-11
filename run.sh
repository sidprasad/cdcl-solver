#!/bin/bash

########################################
############# CSCI 2951-O ##############
########################################
E_BADARGS=65
if [ $# -ne 1 ]
then
	echo "Usage: `basename $0` <input>"
	exit $E_BADARGS
fi
	
input=$1

# Prefer the venv's python executable. Some venvs may have python -> python3
# which can point outside the venv; check `venv/bin/python` first then fall
# back to `venv/bin/python3`.
if [ -x "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
elif [ -x "venv/bin/python3" ]; then
    PYTHON="venv/bin/python3"
else
    echo "Error: Run ./compile.sh first"
    exit 1
fi

# run the solver
$PYTHON src/main.py $input
