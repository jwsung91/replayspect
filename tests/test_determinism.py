"""Same seed, same trace: in-process and across fresh interpreters."""

import os
import subprocess
import sys
from pathlib import Path

import toy


def test_same_seed_same_digest():
    assert toy.run(7).digest() == toy.run(7).digest()


def test_different_seeds_diverge():
    digests = {toy.run(seed).digest() for seed in range(20)}
    assert len(digests) == 20


def test_toy_world_exercises_faults_and_retries():
    tr = toy.run(7)
    kinds = {(e.kind, e.name) for e in tr}
    assert ("fault", "drop") in kinds
    assert any(e.data.get("attempt", 0) > 0 for e in tr)


def test_digest_stable_across_processes_and_hash_seeds():
    here = Path(__file__).parent
    src = here.parent / "src"
    digests = set()
    for hash_seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed,
                   PYTHONPATH=os.pathsep.join([str(src), str(here)]))
        out = subprocess.run([sys.executable, str(here / "toy.py"), "7"],
                             env=env, capture_output=True, text=True, check=True)
        digests.add(out.stdout.strip())
    assert digests == {toy.run(7).digest()}
