# Source this from the repository root: source scripts/dev-env.sh
# A project-local Node installation is optional when Node 22 is already on PATH.
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Create .venv first using docs/LOCAL_DEVELOPMENT.md.'
  return 1
fi
export PATH="$PWD/.tools/node/bin:$PWD/.venv/bin:$PATH"
