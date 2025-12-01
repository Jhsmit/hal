# %%

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dacite import Config as DaciteConfig
from dacite import from_dict
from dacite.data import Data

from hal.utils import clean_types

ROOT = Path(__file__).parent.parent.absolute()


@dataclass
class Cluster:
    address: str
    n_workers: Optional[int] = None
    threads_per_worker: Optional[int] = None
    memory_limit: Optional[str] = None


@dataclass
class Config:
    root: Path = ROOT
    paths: dict[str, Path] = field(default_factory=dict)
    clusters: dict[str, Cluster] = field(default_factory=dict)
    packages: list[str] = field(default_factory=list)

    @property
    def ava(self) -> Path:
        return self.root / "ava"

    @classmethod
    def from_dict(cls, data: Data):
        config = DaciteConfig(type_hooks={Path: lambda v: Path(v).expanduser()})  # type: ignore
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

    def prod_output_path(self, script_folder: str) -> Path:
        pth = cfg.root / "ava" / "prod" / script_folder / "output"
        if pth.exists():
            return pth
        else:
            raise FileNotFoundError("Prod output path does not exist")


# %%
cfg_fpath = ROOT / "config.yaml"
cfg = Config.from_yaml(cfg_fpath)
