"""Shared helpers for the github-triage script tests."""
import importlib.util
import json
import os
import subprocess

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
FAKE_GH_DIR = os.path.join(TESTS_DIR, "fake-gh")


def fake_gh_env(tmpdir, labels=(), author="reporter", authors=None, fail_on=None):
    """Return (env, argv_log_path) with the fake gh first on PATH."""
    log = os.path.join(tmpdir, "gh-argv.jsonl")
    env = dict(os.environ)
    env["PATH"] = FAKE_GH_DIR + os.pathsep + env.get("PATH", "")
    env["GH_ARGV_LOG"] = log
    env["GH_LABELS"] = json.dumps(list(labels))
    env["GH_AUTHOR"] = author
    for number, login in (authors or {}).items():
        env["GH_AUTHOR_%s" % number] = login
    if fail_on:
        env["GH_FAIL_ON"] = fail_on
    return env, log


def run_script(name, args, env, cwd):
    """Run scripts/<name> with args; return the CompletedProcess (text, captured)."""
    return subprocess.run(
        ["python3", os.path.join(SCRIPTS_DIR, name)] + list(args),
        env=env, cwd=cwd, capture_output=True, text=True,
    )


def gh_calls(argv_log_path):
    """Every fake-gh invocation so far, as a list of argv lists."""
    if not os.path.exists(argv_log_path):
        return []
    with open(argv_log_path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_script(name):
    """Import scripts/<name> as a module (the filenames contain hyphens)."""
    path = os.path.join(SCRIPTS_DIR, name)
    module_name = name.replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
