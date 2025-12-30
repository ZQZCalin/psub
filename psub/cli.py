import argparse
import subprocess
from pathlib import Path
import logging
import uuid
from datetime import datetime, timezone
import json
import shutil
import os
from fnmatch import fnmatch
from typing import Any


########################
# Helper funcitons
########################

PSUB_ROOT:      str = "psub-data"
PSUB_READY:     str = ".ready"
PSUB_OUTPUTS:   str = "outputs"
PSUB_SCRIPTS:   str = "scripts"
PSUB_MEMO:      str = "memo.tsv"
PSUB_CONF:      str = "conf.json"

SNAP_IGNORES:   str = "snap_ignores"
SNAP_SYMLINKS:  str = "snap_symlinks"

UUID_LEN: int = 7


def run_git_command(command: str) -> str:
    try:
        return subprocess.check_output(
            command.split(), 
            text=True
        ).strip()
    except FileNotFoundError:
        raise RuntimeError(
            "Git not found. "
            "Please run psub inside a git repository."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command fails: {e.output}")


def get_git_root() -> Path:
    """Safely get the root folder of the current git repo."""
    root = run_git_command("git rev-parse --show-toplevel")
    return Path(root)
    

def get_head_hash() -> str:
    """Safely get the head commit hash."""
    return run_git_command("git rev-parse --short HEAD")


def get_head_msg() -> str:
    """Safely get the head commit message."""
    return run_git_command("git log -1 --pretty=%B")
    

def check_git_clean(verbose: bool=False) -> bool:
    """Check if git worktree is clean."""
    status = run_git_command("git status --porcelain")
    if verbose:
        print("Git worktree status:\n" + status)
    return status == ""


def get_uuid() -> str:
    return uuid.uuid4().hex[:UUID_LEN]


def get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_path_match(path: str | Path, *patterns: str) -> bool:
    """Check if any part in path matches pattern."""
    path = Path(path)
    return any(fnmatch(part, pat.rstrip("/")) for part in path.parts for pat in patterns)


def clone_source_code(
        src_root: str | Path, 
        dst_root: str | Path, 
        snap_ignores: list[str], 
        snap_symlinks: list[str],
) -> None:
    """Clone source code with snap ignores and symlinks."""
    src_root = Path(src_root).resolve()
    dst_root = Path(dst_root).resolve()

    for root, dirs, files in os.walk(src_root):
        src_subdir = Path(root).relative_to(src_root)
        dst_subdir = dst_root / src_subdir

        # If snap_ignore, prune entire sub-tree
        if check_path_match(src_subdir, *snap_ignores):
            dirs[:] = []
            continue

        # If snap_symlink, create symlink and prune sub-tree
        if check_path_match(src_subdir, *snap_symlinks):
            dst_subdir.parent.mkdir(parents=True, exist_ok=True)
            dst_subdir.resolve().symlink_to(src_subdir.resolve())
            dirs[:] = []
            continue
        
        # Otherwise, leave all sub-dirs and handle all files
        dst_subdir.mkdir(parents=True, exist_ok=True)
        for file in files:
            src_file = src_subdir / file
            dst_file = dst_root / src_file
            if check_path_match(src_file, *snap_ignores):
                continue
            if check_path_match(src_file, *snap_symlinks):
                dst_file.resolve().symlink_to(src_file.resolve())
                continue
            shutil.copy2(src_file, dst_file)

    print(f"Successfully cloned from {src_root} to {dst_root}.")


def create_snapshot(output_dir: str | Path, commit_hash: str, commit_msg: str) -> None:
    """
    Creates a snapshot when copying the source code of a commit hash
    for the first time. 
    """
    root_dir = get_git_root()
    output_dir = Path(output_dir)
    paths = {
        "code":     output_dir / "code",
        "exp":      output_dir / "experiments",
        "conf":     output_dir / "conf.json",
        "meta":     output_dir / "meta.txt",
        "ready":    output_dir / ".ready",
    }

    if paths["ready"].exists():
        logging.info(f"INFO: snapshot already created at {output_dir}.")
        return
    
    output_dir.mkdir(exist_ok=True)

    meta = (
        f"timestamp:    {get_timestamp()}\n"
        f"commit-hash:  {commit_hash}\n"
        f"commit-msg:   \n{commit_msg}\n"
    )
    paths["meta"].write_text(meta)

    src_conf = root_dir / PSUB_ROOT / PSUB_CONF
    with src_conf.open("r", encoding="utf-8") as f:
        conf: dict = json.load(f)
        snap_ignores: list[str] = conf.get(SNAP_IGNORES, [])
        snap_symlinks: list[str] = conf.get(SNAP_SYMLINKS, [])
    shutil.copy2(src_conf, paths["conf"])

    if PSUB_ROOT not in snap_ignores:
        snap_ignores.append(PSUB_ROOT)
    clone_source_code(root_dir, paths["code"], snap_ignores, snap_symlinks)

    paths["exp"].mkdir(exist_ok=True)

    paths["ready"].touch()
    print(f"Successfully snapshot source code at {output_dir}.")


def create_memo(path: str | Path) -> None:
    """Creates an empty memo.tsv with header row."""
    path = Path(path)
    if path.exists():
        raise ValueError(f"Memo already exists at {path}.")
    memo_header = "timestamp\tcommit\texp_name\toutput\tnotes\n"
    path.write_text(memo_header)


def append_memo(path: str | Path, timestamp: str, commit: str, 
                exp_name: str, output: str | Path, notes: str) -> None:
    """Append a new row to memo.tsv."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Memo does not exist at {path}.")
    content = f"{timestamp}\t{commit}\t{exp_name}\t{output}\t{notes}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


def sync_conf(src: str | Path, dst: str | Path, 
              overwrite: bool=False, force: bool=False) -> None:
    """Sync src .gitignore to dst conf.json.
    
    Args:
        overwrite: defaults merge src to snap_ignores; if true, overwrite snap_ignore
        force: if true, reconstruct conf from scratch
    """
    src = Path(src)
    dst = Path(dst)

    if not dst.exists() or force:
        conf = {
            SNAP_IGNORES: [],
            SNAP_SYMLINKS: [],
        }
    else:
        with dst.open("r", encoding="utf-8") as f:
            conf = json.load(f)

    if not src.exists():
        snap_ignores = []
    else:
        with src.open("r", encoding="utf-8") as f:
            snap_ignores = [
                line.strip() for line in f
                if line.strip() and not line.startswith("#")
            ]

    if overwrite:
        conf[SNAP_IGNORES] = snap_ignores
    else:
        conf[SNAP_IGNORES] = list(set(conf[SNAP_IGNORES]) | set(snap_ignores))

    with dst.open("w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)
    
    print(f"Successfully updated config at {dst} from {src}.")


########################
# CLI functions
########################

def check_psub_ready() -> bool:
    """Check if psub is initialized."""
    psub_ready = get_git_root() / PSUB_ROOT / PSUB_READY
    return psub_ready.exists()


def psub_init_cli(args) -> None:
    """
    Handle: psub init

    Initializes psub-data folder
    psub-data/
    |-- memo.tsv            # snapshots submission info
    |-- conf.json           # customized configs (contains snap_ignore and snap_symlinks)
    |-- scripts/            # customized submission scripts
    |-- outputs/            # experiment outputs
    """
    root_dir = get_git_root()
    psub_dir = root_dir / PSUB_ROOT
    paths = {
        "ready":    psub_dir / PSUB_READY,
        "memo":     psub_dir / PSUB_MEMO,
        "conf":     psub_dir / PSUB_CONF,
        "scripts":  psub_dir / PSUB_SCRIPTS,
        "outputs":  psub_dir / PSUB_OUTPUTS,
    }

    if paths["ready"].exists():
        logging.info("INFO: psub is already initialized.")
        return
    
    psub_dir.mkdir(exist_ok=True)

    create_memo(paths["memo"])

    sync_conf(root_dir / ".gitignore", paths["conf"])

    paths["scripts"].mkdir(exist_ok=True)
    paths["outputs"].mkdir(exist_ok=True)

    paths["ready"].touch()
    print("Sucessfully initialized psub project.")


def psub_run_cli(
        script: str | Path, 
        commit_hash: str=None,
        exp_name: str=None,
        notes: str=None,
) -> None:
    """
    Handle: psub run <script> <exp> <commit>
    """
    if not check_psub_ready():
        raise RuntimeError("Please initialize psub via `psub init` first.")
    
    if not check_git_clean():
        check_git_clean(verbose=True)
        raise RuntimeError("Please clean and commit above worktree first.")

    script = Path(script)
    is_head_commit = commit_hash is None
    commit_hash = commit_hash or get_head_hash()
    exp_name = f"{exp_name or 'exp'}-{get_uuid()}"

    output_root = get_git_root() / PSUB_ROOT / PSUB_OUTPUTS
    commit_dir = output_root / f"commit-{commit_hash}"
    exp_dir = commit_dir / "experiments" / exp_name

    if exp_dir.exists():
        raise ValueError(f"Output path already exists at {exp_dir}.")

    # Snapshot source code if necessary.
    if is_head_commit:
        create_snapshot(commit_dir, commit_hash, get_head_msg())
    elif not (commit_dir / ".ready").exists():
        raise RuntimeError(
            f"{commit_dir} doesn't have snapshot. "
            "Please specify an existing commit-hash."
        )
    
    # Run submission script.
    exp_dir.mkdir()
    shutil.copy2(script, exp_dir / Path("script").with_suffix(script.suffix))
    append_memo(
        get_git_root() / PSUB_ROOT / PSUB_MEMO,
        get_timestamp(), commit_hash, exp_name, exp_dir, notes
    )
    subprocess.run(["bash", script.resolve()], check=True)


def psub_sync_cli(overwrite: bool=False, force: bool=False) -> None:
    """Handle: psub sync"""
    root_dir = get_git_root()
    src = root_dir / ".gitignore"
    dst = root_dir / PSUB_ROOT / PSUB_CONF
    sync_conf(src, dst, overwrite, force)


########################
# CLI Argparser
########################

def main():
    parser = argparse.ArgumentParser(prog="psub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. psub init
    psub_init = subparsers.add_parser(
        "init", help="initialize psub in current git repo")
    psub_init.set_defaults(func=psub_init_cli)

    # 2. psub run <script> <exp> <commit>
    psub_run = subparsers.add_parser(
        "run", help="run a submission script via psub")
    psub_run.add_argument(
        "script", 
        help="path of submission script")
    psub_run.add_argument(
        "-c", "--commit_hash", 
        help="commit hash, defaults to head commit if not specified")
    psub_run.add_argument(
        "-e", "--exp_name", 
        help="experiment name")
    psub_run.add_argument(
        "-n", "--notes",
        help="additional experiment notes")
    psub_run.set_defaults(
        func=lambda args: psub_run_cli(
            args.script, 
            args.commit_hash,
            args.exp_name,
            args.notes,
        )
    )

    # 3. psub sync
    psub_sync = subparsers.add_parser(
        "sync", help="sync .gitignore to conf.json")
    psub_sync.add_argument(
        "--overwrite", action="store_true",
        help="overwrite with .gitignore (defauts to merging)")
    psub_sync.add_argument(
        "--force", action="store_true",
        help="reconstruct conf.json (use with caution)")
    psub_sync.set_defaults(
        func=lambda args: psub_sync_cli(args.overwrite, args.force)
    )

    # Parse + dispatch
    args = parser.parse_args()
    args.func(args)
