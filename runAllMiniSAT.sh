#!/bin/bash

########################################
############# CSCI 2951-O ##############
########################################
E_BADARGS=65
if [ $# -ne 3 ]
then
	echo "Usage: `basename $0` <inputFolder/> <timeLimit> <logFile>"
	echo "Description:"
	echo -e "\t This script makes calls to minisat for all the files in the given inputFolder/"
	echo -e "\t Each run is subject to the given time limit in seconds (uses GNU timeout)."
	echo -e "\t Last line of each run is appended to the given logFile in the same JSON format as ./run.sh." 
	echo -e "\t If a run fails (timeout or error), the file name is appended to the logFile with --'s as time and result."
	echo -e "\t If the logFile already exists, the run is aborted."
	exit $E_BADARGS
fi

# Parameters
inputFolder=$1
timeLimit=$2
logFile=$3

# Append slash to the end of inputFolder if it does not have it
lastChar="${inputFolder: -1}"
if [ "$lastChar" != "/" ]; then
    inputFolder=$inputFolder/
fi

# Terminate if the log file already exists
[ -f $logFile ] && echo "Logfile $logFile already exists, terminating." && exit 1

# Create the log file
touch $logFile

# Run on every file, get the last line, append to log file
for f in $inputFolder*.*
do
    fullFileName=$(realpath "$f")
    echo "Running $fullFileName"

    # record start time (portable across macOS / Linux)
    start_time=$(python -c 'import time; print(time.time())')

    # run minisat with timeout; redirect stdout/stderr to a temp file
    timeout $timeLimit minisat "$fullFileName" minisat.out > minisat.stdout 2>&1
    returnValue="$?"

    # record end time
    end_time=$(python -c 'import time; print(time.time())')

    # compute elapsed with two decimal places (one-line Python call — portable)
    elapsed=$(python -c "import sys; print(f'{float(sys.argv[2]) - float(sys.argv[1]):.2f}')" "$start_time" "$end_time")

    if [[ "$returnValue" = 10 ]]; then
        # minisat signals SAT with exit code 10
        instance=$(basename "$fullFileName")
        echo "{\"Instance\": \"$instance\", \"Time\": \"$elapsed\", \"Result\": \"SAT\"}" >> $logFile
    elif [[ "$returnValue" = 20 ]]; then
        # minisat signals UNSAT with exit code 20
        instance=$(basename "$fullFileName")
        echo "{\"Instance\": \"$instance\", \"Time\": \"$elapsed\", \"Result\": \"UNSAT\"}" >> $logFile
    else
        # any other return code -> treat as failure / timeout
        echo Error
        instance=$(basename "$fullFileName")
        echo "{\"Instance\": \"$instance\", \"Time\": \"--\", \"Result\": \"--\"}" >> $logFile
    fi

    rm -f minisat.stdout minisat.out
done
