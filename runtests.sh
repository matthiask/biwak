#!/bin/sh
# ./runtests.sh [labels and options of manage.py test]: in parallel, one
# process per CPU (--parallel 1 runs serially). COVERAGE=1 ./runtests.sh
# measures the coverage too (decided 2026-11-21: nothing needs it always).
set -ex
# The end-to-end tests and biwak/test_css.py need the production bundle in
# static/ (the build takes about a second)
mise exec -- yarn rspack build --mode production
if [ -n "$COVERAGE" ]; then
  uv run coverage erase
  PYTHONWARNINGS=all uv run coverage run ./manage.py test -v 2 --keepdb --parallel auto $*
  uv run coverage combine -q
  uv run coverage report
else
  PYTHONWARNINGS=all uv run ./manage.py test -v 2 --keepdb --parallel auto $*
fi
