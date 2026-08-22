"""The five processes.

Each subpackage is a separately deployable process with its own entry point.
They share `graphrec` and, by the import-linter contract in pyproject.toml,
nothing else — `job_worker` importing a control-plane request handler would pass
review once and be load-bearing forever.
"""
