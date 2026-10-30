"""Capture the existing opt-in suite without changing the repository tests."""

import dataclasses
import datetime
import json
import os
import random
from pathlib import Path

import pytest


STATE = {"engine": os.environ["BENCH_ENGINE"], "cases": {}, "benchmarks": []}
CURRENT = None


def pytest_configure(config):
    global CURRENT
    from test.db.cypher_cases import performance

    original = performance.benchmark

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        STATE["benchmarks"].append({"nodeid": CURRENT, **dataclasses.asdict(result)})
        return result

    performance.benchmark = measured
    random.seed(20261029)
    STATE["started_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()


def pytest_runtest_setup(item):
    global CURRENT
    CURRENT = item.nodeid


def pytest_runtest_logreport(report):
    if report.when != "call" and not report.failed:
        return
    STATE["cases"][report.nodeid] = {
        "outcome": report.outcome,
        "phase": report.when,
        "seconds": report.duration,
        "stdout": report.capstdout,
        "stderr": report.capstderr,
        "failure": report.longreprtext if report.failed else None,
    }
    target = Path('/evidence') / ("suite-" + STATE["engine"] + ".json")
    target.write_text(json.dumps(STATE, indent=2) + "\n")


def pytest_sessionfinish(session, exitstatus):
    STATE["exit_status"] = int(exitstatus)
    STATE["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target = Path('/evidence') / ("suite-" + STATE["engine"] + ".json")
    target.write_text(json.dumps(STATE, indent=2) + "\n")
