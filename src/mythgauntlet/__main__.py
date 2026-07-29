import sys

from mythgauntlet.cli import main

# The __main__ guard is REQUIRED: the orchestrator uses multiprocessing, and Windows `spawn`
# re-imports this module in every worker. Without the guard, workers would re-run the CLI and
# spawn recursively. With it, workers import cleanly (as __mp_main__) and only the real launch
# executes main().
if __name__ == "__main__":
    sys.exit(main())
