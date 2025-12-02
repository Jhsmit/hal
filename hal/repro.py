import atexit
import traceback
import distutils.sysconfig as sysconfig
import importlib
import pkgutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Callable, Generator, Iterable, Optional
import warnings
import types


import watermark

from hal.config import cfg

ExcepthookType = Callable[
    [type[BaseException], BaseException, types.TracebackType | None], None
]


MAX_DATA_DIR_FILES = 50_000


def data_dir_to_str(data_dir: Path) -> str:
    all_files = [
        f.relative_to(data_dir).as_posix() for f in data_dir.glob("**/*") if f.is_file()
    ]

    s = ""

    if not all_files:
        return s

    s += f"Data directory: {data_dir.as_posix()}\n"

    if len(all_files) > MAX_DATA_DIR_FILES:
        s += f"  (showing first {MAX_DATA_DIR_FILES} of {len(all_files)} files)\n"

    file_str = "\n".join(all_files[:MAX_DATA_DIR_FILES])
    s += file_str + "\n"
    return s


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


def fetch_git_status(repo_path: Path = cfg.root) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.split("\n")

    return lines


EXCEPTION: (
    tuple[type[BaseException], BaseException, types.TracebackType | None] | None
) = None


def excepthook(
    exec_type: type[BaseException],
    value: BaseException,
    traceback: types.TracebackType | None,
):
    global EXCEPTION
    EXCEPTION = (exec_type, value, traceback)
    sys.__excepthook__(exec_type, value, traceback)


def _reproduce(
    globals_: dict,
    packages: Optional[Iterable[str]] = None,
    external_data_paths: Optional[dict[str, Path]] = None,
    **watermark_kwargs,
):
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

    # Remove hal / builtins
    combined -= {"hal", "builtins"}

    mark_kwargs = dict(
        author="Jochem H. Smit",
        current_time=True,
        current_date=True,
        timezone=True,
        updated=True,
        python=True,
        machine=True,
    )

    unclean = ""
    if is_git_repo():
        mark_kwargs.update(
            githash=True,
            gitbranch=True,
        )
        lines = fetch_git_status()
        if lines:
            unclean = "\n".join(lines)
            counts = {
                "untracked": sum(1 for line in lines if line.startswith("??")),
                "modified": sum(1 for line in lines if "M" in line[:2]),
                "added": sum(1 for line in lines if line.startswith("A ")),
                "deleted": sum(1 for line in lines if "D" in line[:2]),
                "renamed": sum(1 for line in lines if line.startswith("R ")),
            }
        warnings.warn(
            f"There are {counts['untracked']} untracked, {counts['modified']} modified, {counts['added']} added, {counts['deleted']} deleted, and {counts['renamed']} renamed files in the git repository."
        )
    else:
        warnings.warn("Current directory is not a git repository.")

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

    if unclean:
        mark += "\n\n"
        mark += "Git repository is unclean:\n"
        mark += unclean

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

    external_keys = sorted(cfg.paths._used_keys)
    external_paths = (
        (external_data_paths or {})
        | {"_root_data": cfg.root / "data", "_output": output_path}
        | {k: cfg.paths[k] for k in external_keys}
    )

    script_root = script_path.parent
    with zipfile.ZipFile(
        output_path / "_rpr.zip", "w", zipfile.ZIP_DEFLATED
    ) as rpr_zip:
        py_files = script_root.glob("**/*.py")
        for f in py_files:
            rpr_zip.write(f, Path("scripts") / f.relative_to(script_root))
        rpr_zip.writestr("watermark.txt", mark)

        rpr_zip.writestr("uv_pip_freeze.txt", freeze_no_editable)
        if freeze.stderr:
            rpr_zip.writestr("uv_pip_freeze_error.txt", freeze.stderr)

        # copy root lockfile:
        lockfile = cfg.root / "uv.lock"
        if lockfile.exists():
            rpr_zip.write(lockfile, Path("uv.lock"))

        # write general use toolbox directory
        toolbox_dir = cfg.root / "ava"
        if toolbox_dir.exists():
            zipdir(toolbox_dir, rpr_zip, root="ava")

        # Check if script had an exception
        if EXCEPTION is not None:
            error_type, error_value, error_traceback = EXCEPTION
            s = "\n".join(
                traceback.format_exception(error_type, error_value, error_traceback)
            )

            with zipfile.ZipFile(
                output_path / "_rpr.zip", "w", zipfile.ZIP_DEFLATED
            ) as rpr_zip:
                rpr_zip.writestr("error.txt", s)

                # write the contents of (external) data directories

    with zipfile.ZipFile(
        output_path / f"{script_path.stem}_data_sources.zip", "w", zipfile.ZIP_DEFLATED
    ) as rpr_zip:
        for k, v in external_paths.items():
            s = data_dir_to_str(v)
            if s:
                rpr_zip.writestr(f"{k}.txt", s)

    return


def reproduce(
    globals_: dict,
    packages: Optional[Iterable[str]] = None,
    external_data_paths: Optional[dict[str, Path]] = None,
    excepthook: ExcepthookType | None = excepthook,
    **watermark_kwargs,
) -> Path:
    """
    Reproduce the current script environment by creating a reproducibility package.

    This function collects information about the current script, its dependencies,
    and the environment, then packages them into a zip file for reproducibility.

    Args:
        globals_ (dict): The globals dictionary from the calling script.
        packages (Optional[Iterable[str]]): Additional packages to include.
        external_data_paths (Optional[dict[str, Path]]): External data directories to include.
        **watermark_kwargs: Additional keyword arguments for the watermark.

    Returns:
        Path: The path to the output directory containing the reproducibility package.
    """
    script_path = Path(globals_["__file__"])
    output_path = script_path.parent / "output"
    output_path.mkdir(exist_ok=True, parents=True)

    if excepthook is not None:
        sys.excepthook = excepthook

    atexit.register(
        _reproduce,
        globals_=globals_.copy(),
        packages=packages,
        external_data_paths=external_data_paths,
        **watermark_kwargs,
    )

    return output_path
