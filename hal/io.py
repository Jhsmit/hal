"""functions used to save results to disk"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable
import narwhals as nw
import yaml

from hal.utils import clean_types

if TYPE_CHECKING:
    import pandas as pd  # type: ignore
    import polars as pl  # type: ignore
    from matplotlib.figure import Figure  # type: ignore
    from smitfit.fitresult import FitResult  # type: ignore


SAVEFIG_KWARGS: dict[str, Any] = dict(dpi=300, transparent=True)


def all_exist(file_paths: Iterable[Path]) -> bool:
    return all([x.exists() for x in file_paths])


@dataclass
class Output:
    save_dir: Path
    files: list[str]
    overwrite: bool = False

    def __post_init__(self):
        self.save_dir.mkdir(exist_ok=True, parents=True)

    @property
    def outputs(self) -> list[Path]:
        return [self.save_dir / f for f in self.files]

    @property
    def done(self) -> bool:
        return all_exist(self.outputs)

    @property
    def skip(self) -> bool:
        if self.overwrite:
            return False
        return self.done

    def __getitem__(self, item: str) -> Path:
        if item in self.files:
            return self.save_dir / item
        raise KeyError(item)

    def status(self) -> str:
        s = ""
        for o, f in zip(self.outputs, self.files):
            s += f"{f}: {o.exists()}\n"
        return s


def save_and_close(
    fig: Figure, path: Path, extensions: list[str] | str | None = None, close=True
) -> None:
    if isinstance(extensions, str):
        extensions = [extensions]
    elif extensions is None:
        extensions = [".png", ".pdf"]
    elif isinstance(extensions, list):
        pass
    else:
        raise ValueError("ext must be a string or list of strings")

    for ext in extensions:
        fig.savefig(str(path.with_suffix(ext)), **SAVEFIG_KWARGS)

    if close:
        import matplotlib.pyplot as plt  # type: ignore

        plt.close(fig)


def save_csv(df: pl.DataFrame | pd.DataFrame | nw.DataFrame, file_path: Path):
    nw.from_native(df).write_csv(file_path)


def save_fig(
    fig: Figure, file_path: Path, extensions: list[str] | str | None = None, close=True
):
    """save figure to filepath with extensions"""
    save_and_close(fig, file_path, extensions=extensions, close=close)


def save_yaml(data, file_path: Path, clean: bool = True):
    if clean:
        data = clean_types(data)

    file_path.write_text(yaml.dump(data))


def save_str(s: str, file_path: Path):
    file_path.write_text(s)


def save_fitresult(result: FitResult, file_path: Path) -> None:
    result.to_yaml(file_path)
