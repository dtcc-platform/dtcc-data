#!/usr/bin/env bash

lasdir=$1
outdir=$2

echo "Importing LAS data from $lasdir to $outdir"

# Load LAS data
find "$lasdir" -name "*.laz" | parallel -j4 dtcc-import-elevation-data {} "$outdir"

