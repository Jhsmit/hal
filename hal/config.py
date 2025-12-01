# %%

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, TypeVar, Generic

import yaml
from dacite import Config as DaciteConfig
from dacite import from_dict
from dacite.data import Data

from hal.utils import clean_types
import os
import sys


def has_rootfiles(pth: Path) -> bool:
    root_files = ["pyproject.toml", "config.yaml"]
    return all((pth / f).exists() for f in root_files)


def find_project_root() -> Path:
    """Find the project root by looking for specific files in parent directories."""
    if env_root := os.getenv("HAL_PROJECT_ROOT"):
        return Path(env_root).absolute()

    executable_path = Path(sys.executable)
    folder = executable_path.parts[-3]  # go up two levels
    maybe_root = Path(*executable_path.parts[:-3])
    if folder == ".venv" and has_rootfiles(maybe_root):
        return maybe_root.absolute()

    current_path = Path.cwd().absolute()
    for parent in [current_path] + list(current_path.parents):
        if has_rootfiles(parent):
            return parent

    raise FileNotFoundError(
        "Project root with required files not found. Configure manually by setting HAL_PROJECT_ROOT environment variable."
    )


ROOT = find_project_root()


@dataclass
class Cluster:
    address: str
    n_workers: Optional[int] = None
    threads_per_worker: Optional[int] = None
    memory_limit: Optional[str] = None


K = TypeVar("K")
V = TypeVar("V")


class MemoryDict(dict, Generic[K, V]):
    """dict which keeps track of accessed keys"""

    RESERVED_KEYS = frozenset(["_root_data"])

    def __init__(self, *args, **kwargs):
        initial_data = dict(*args, **kwargs)
        if reserved := self.RESERVED_KEYS & initial_data.keys():
            raise KeyError(f"Reserved keys cannot be used: {reserved}")

        super().__init__(initial_data)
        self._used_keys: set[K] = set()

    def _check_key(self, key: K) -> None:
        if key in self.RESERVED_KEYS:
            raise KeyError(f"'{key}' is a reserved key and cannot be used.")

    def __setitem__(self, key: K, value: V) -> None:
        self._check_key(key)
        super().__setitem__(key, value)

    def __getitem__(self, key: K) -> V:
        self._used_keys.add(key)
        value = super().__getitem__(key)
        return value

    def update(self, *args, **kwargs) -> None:
        """Override update to check for reserved keys"""
        new_data = dict(*args, **kwargs)
        if reserved := self.RESERVED_KEYS & new_data.keys():
            raise KeyError(f"Reserved keys cannot be used: {reserved}")
        super().update(new_data)


@dataclass
class Config:
    root: Path = ROOT
    paths: MemoryDict[str, Path] = field(default_factory=MemoryDict)
    clusters: dict[str, Cluster] = field(default_factory=dict)
    packages: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Data):
        config = DaciteConfig(
            type_hooks={Path: lambda v: Path(v).expanduser()}, cast=[MemoryDict]
        )  # type: ignore
        return from_dict(cls, data, config)

    @classmethod
    def from_yaml(cls, fpath: Path):
        data = yaml.safe_load(fpath.read_text())
        return cls.from_dict(data)

    def to_yaml(self, fpath: Path) -> None:
        s = yaml.dump(clean_types(asdict(self)), sort_keys=False)
        fpath.write_text(s)

    def update(self, data: Data):
        new_data = {**self.__dict__, **data}

        # we use `from_dict` to cast to the correct types
        new_cfg = Config.from_dict(new_data)
        vars(self).update(vars(new_cfg))

    def output_path(self, script_folder: str) -> Path:
        pth = cfg.root / "src" / script_folder / "output"
        if pth.exists():
            return pth
        else:
            raise FileNotFoundError("Output path does not exist")


# %%
cfg_fpath = ROOT / "config.yaml"
cfg = Config.from_yaml(cfg_fpath)
