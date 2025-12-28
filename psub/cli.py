import argparse
import subprocess


def get_git_root():
    git_root = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True
    )


def setup_repo(args):
    """
    Handle: psub init
    """
    print("testing setup_repo")


def run_script(args):
    """
    Handle: psub run <script> <exp> <commit>
    """
    print("testing run script")
    print(args)


def main():
    parser = argparse.ArgumentParser(prog="psub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # psub init
    psub_init = subparsers.add_parser(
        "init", help="Initialize qsub in current git repo.")
    psub_init.set_defaults(
        func=setup_repo)

    # ------------------------
    # psub run <script> <exp> <commit>
    # ------------------------
    p_run = subparsers.add_parser(
        "run", help="Run a psub script")
    p_run.add_argument(
        "script", help="")
    p_run.add_argument("-n", "--exp_name")
    p_run.add_argument("-h", "--commit_hash")
    p_run.set_defaults(
        func=lambda args: run_script(args.script, args.exp_name, args.commit_hash)
    )

    # Parse + dispatch
    args = parser.parse_args()
    args.func(args)

    # psub run <script> <exp> <commit>


if __name__ == "__main__":
    out = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True
    )
    print(out)