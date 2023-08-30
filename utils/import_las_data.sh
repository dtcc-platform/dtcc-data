#!/usr/bin/env bash

lasdir=$1
outdir=$2

echo "Importing LAS data from $lasdir to $outdir"

# Load LAS data. Randomize order to spread the write load across hdf5 files for parallel writes
find "$lasdir" -name "*.laz" | sort -R | parallel -j12 dtcc-import-elevation-data {} "$outdir"

