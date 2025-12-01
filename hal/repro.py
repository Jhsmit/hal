import distutils.sysconfig as sysconfig
import importlib
import pkgutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Generator, Iterable, Optional
import warnings

import watermark

from hal.config import cfg


def gen_imports(globals_: dict) -> Generator:
    for name, val in globals_.items():
        if isinstance(val, ModuleType):
            base_module = val.__name__.split(".")[0]
            yield base_module
        else:
            try:
                yield val.__module__.split(".")[0]
            except AttributeError:
                pass


def zipdir(path: Path, zipf: zipfile.ZipFile, root: str = ""):
    for file_path in path.glob("**/*"):
        if "__pycache__" in file_path.parts:
            continue

        root = root or path.stem
        if file_path.is_file():
            relpath = file_path.relative_to(path)
            zipf.write(file_path, Path(root) / relpath)


def is_git_repo():
    try:
        # Run git command to check if we're in a git repository
        subprocess.check_output(
            ["git", "rev-parse", "--is-inside-work-tree"], stderr=subprocess.STDOUT
        )
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        # Git command not found
        return False


def warn_git_not_clean(repo_path: Path = cfg.root):
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.split("\n")
    num_uncommitted = sum(1 for line in lines if line.startswith("??"))
    num_modified = sum(
        1 for line in lines if line.startswith(" M") or line.startswith("M ")
    )

    warnings.warn(
        f"There are {num_uncommitted} uncommitted and {num_modified} modified files in the git repository."
    )


def reproduce(
    globals_: dict,
    packages: Optional[Iterable[str]] = None,
    **watermark_kwargs,
) -> Path:
    script_path = Path(globals_["__file__"])
    output_path = script_path.parent / "output"
    output_path.mkdir(exist_ok=True, parents=True)

    # get editable packages

    editable_modules = []
    if (cfg.root / "editable").exists():
        editable_modules = [f for f in (cfg.root / "editable").iterdir() if f.is_dir()]

    pkgs = pkgutil.iter_modules(editable_modules)
    editable_packages = {p.name for p in pkgs}

    # combine user packages, imported packages and editable packages
    combined = set(packages or []) | set(gen_imports(globals_)) | editable_packages

    # Remove builtins
    combined -= {sys.builtin_module_names}

    # Remove standard library
    stdlib_pth = sysconfig.get_python_lib(standard_lib=True)
    stdlib = {p.stem.replace(".py", "") for p in Path(stdlib_pth).iterdir()}
    combined -= stdlib

    # Remove hal/ava
    combined -= {"hal", "builtins", "ava"}

    mark_kwargs = dict(
        author="Jochem H. Smit",
        current_time=True,
        current_date=True,
        timezone=True,
        updated=True,
        python=True,
        machine=True,
    )

    if is_git_repo():
        mark_kwargs.update(
            githash=True,
            gitbranch=True,
        )
        warn_git_not_clean()

    mark_kwargs.update(watermark_kwargs)
    mark = watermark.watermark(
        globals_=globals_,
        packages=",".join(sorted(combined)),
        **mark_kwargs,  # type: ignore
    )
    # get __version__ manually for selected packages
    versions = {}
    for package in packages or []:
        imported = importlib.import_module(package)
        try:
            versions[package] = imported.__version__
        except AttributeError:
            pass

    # write to mark string
    if versions:
        mark += "\n\n"
        mark += "Additional version information:\n"

    for package, version in versions.items():
        mark += f"\n{package}=={version}"

    # Run the command and capture the output
    freeze = subprocess.run(
        ["uv", "pip", "freeze", "--no-color"],
        capture_output=True,
        text=True,
        env={**subprocess.os.environ, "NO_COLOR": "1"},  # type: ignore
    )
    freeze_str = freeze.stdout
    # remove editable packages from freeze output
    lines = [line for line in freeze_str.splitlines() if not line.startswith("-e")]
    freeze_no_editable = "\n".join(lines)

    # write to root freeze.txt file
    if freeze_no_editable:
        freeze_file = cfg.root / "freeze.txt"
        with open(freeze_file, "w") as f:
            f.write("# uv pip freeze output generated at ")
            f.write(datetime.now().isoformat())
            f.write("\n")
            f.write(freeze_no_editable)

    if freeze.stderr:
        freeze_error_file = cfg.root / "freeze_stderr.txt"
        with open(freeze_error_file, "w") as f:
            f.write("# uv pip freeze stderr output generated at ")
            f.write(datetime.now().isoformat())
            f.write("\n")
            f.write(freeze.stderr)

    script_root = script_path.parent
    with zipfile.ZipFile(
        output_path / "_rpr.zip", "w", zipfile.ZIP_DEFLATED
    ) as rpr_zip:
        py_files = script_root.glob("**/*.py")
        for f in py_files:
            rpr_zip.write(f, f.relative_to(script_root))
        rpr_zip.writestr("watermark.txt", mark)

        rpr_zip.writestr("pip_freeze.txt", freeze_str)
        if freeze.stderr:
            rpr_zip.writestr("pip_freeze_error.txt", freeze.stderr)

        toolbox_dir = cfg.root / "ava"
        if toolbox_dir.exists():
            zipdir(toolbox_dir, rpr_zip, root="_ava")

    return output_path
