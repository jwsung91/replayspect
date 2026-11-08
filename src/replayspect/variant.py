"""Implementation variants: another implementation of a registered system, loaded from outside the package.

A variant replaces how a system runs and nothing else. The system's contracts,
protocol description, link profile and run length stay as registered, so a
variant run is judged exactly like a run of the system itself.

A spec names a Python file or module and an attribute in it:
``path/to/file.py:NAME`` or ``package.module:NAME``. The attribute is a
:class:`Variant` (or any object with the same two attributes). Loading a spec
runs its code: load only files you trust.

What a variant must do, so that its traces compare with the system's:

* build its run from the package's own parts: :class:`~replayspect.sim.scheduler.Scheduler`,
  :class:`~replayspect.sim.link.Channel` and :class:`~replayspect.trace.Trace`, so events
  are recorded and digested the same way;
* use the link profile it is given, not one of its own;
* return the :class:`~replayspect.trace.Trace` it recorded.

A variant that behaves like the registered implementation gives the same
digest for every seed and plan. The tests check this with a neutral variant.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from replayspect.sim.link import ChannelProfile, FaultPlan
from replayspect.trace import Trace

#: (seed, profile, plan, until_us) -> trace
VariantRun = Callable[[int, ChannelProfile, "FaultPlan | None", int], Trace]


@dataclass(frozen=True)
class Variant:
    #: Name of the registered system this variant implements, e.g. ``"lift.v0"``.
    system: str
    run: VariantRun


@dataclass(frozen=True)
class VariantRef:
    """Where a variant came from: the spec as given and the digest of the file it names."""

    spec: str
    #: SHA-256 of the file that defines the attribute. It covers that file only, not what it imports.
    sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"spec": self.spec, "sha256": self.sha256}


class VariantError(ValueError):
    pass


def _split(spec: str) -> tuple[str, str]:
    where, sep, name = spec.rpartition(":")
    if not sep or not where or not name.isidentifier():
        raise VariantError(f"bad variant spec {spec!r}; expected path/to/file.py:NAME or package.module:NAME")
    return where, name


def _load_file(path: Path) -> Any:
    if not path.is_file():
        raise VariantError(f"variant file not found: {path}")
    resolved = path.resolve()
    # Keyed by path and content, so an edited file is loaded again, not served from the cache.
    key = str(resolved).encode() + b"\0" + resolved.read_bytes()
    mod_name = "replayspect_variant_" + hashlib.sha256(key).hexdigest()[:16]
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, resolved)
    if spec is None or spec.loader is None:
        raise VariantError(f"cannot load variant file {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    # Let the file import its neighbours (helpers kept next to it).
    sys.path.insert(0, str(resolved.parent))
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[mod_name]
        raise
    finally:
        sys.path.remove(str(resolved.parent))
    return module


def file_digest(path: str | Path | None) -> str | None:
    if path is None or not Path(path).is_file():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_variant(spec: str) -> tuple[Variant, VariantRef]:
    """Load the variant a spec names, and record where it came from."""
    where, name = _split(spec)
    if where.endswith(".py"):
        module = _load_file(Path(where))
    else:
        try:
            module = importlib.import_module(where)
        except ImportError as exc:
            raise VariantError(f"cannot import variant module {where!r}: {exc}") from None
    try:
        obj = getattr(module, name)
    except AttributeError:
        raise VariantError(f"{where} has no attribute {name!r}") from None
    system, run = getattr(obj, "system", None), getattr(obj, "run", None)
    if not isinstance(system, str) or not callable(run):
        raise VariantError(f"{spec} is not a variant: it needs a 'system' name and a 'run' function")
    return Variant(system, run), VariantRef(spec, file_digest(getattr(module, "__file__", None)))


def variant_run(variant: Variant, profile: ChannelProfile) -> Callable[[int, FaultPlan | None, tuple[str, ...], int], Trace]:
    """Wrap a variant as a system run function (seed, plan, mutants, until_us) -> trace."""

    def run(seed: int, plan: FaultPlan | None, mutants: tuple[str, ...], until_us: int) -> Trace:
        if mutants:
            raise ValueError("a variant run takes no mutants")
        trace = variant.run(seed, profile, plan, until_us)
        if type(trace) is not Trace:
            raise TypeError(f"variant for {variant.system} returned {type(trace).__name__}, not the package's Trace")
        return trace

    return run
