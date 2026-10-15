#!/bin/bash
# run_all.sh T1 T2 ... : run every backend for each template then build sheets + table
cd /workspace/pm6-eval/template
BACKENDS=${BACKENDS:-v48,pm6,pm6-svg}
for t in "$@"; do
  for b in ${BACKENDS//,/ }; do
    venv/bin/python tools/run_case.py specs/$t.json $b runs/$t/$b
  done
done
BACKENDS=$BACKENDS venv/bin/python tools/compare.py "$@"
