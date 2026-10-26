"""Beginner setup checker.  Run:  python check_setup.py        (free)
                              or:  python check_setup.py --invoke   (one tiny Bedrock call, costs a fraction of a cent)
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def ok(msg): print(f"[ OK ] {msg}")
def bad(msg): print(f"[FAIL] {msg}")


def main() -> int:
    problems = 0
    if sys.version_info >= (3, 10):
        ok(f"Python {sys.version.split()[0]}")
    else:
        bad("Python 3.10 or newer is required"); problems += 1
    for mod in ("streamlit", "strands", "pypdf", "boto3", "dotenv"):
        try:
            __import__(mod); ok(f"package '{mod}' installed")
        except ImportError:
            bad(f"package '{mod}' missing - run: pip install -r requirements.txt"); problems += 1
    if problems:
        return 1

    from errors import friendly_aws_message
    from storage import StorageError, get_store

    mode = os.getenv("STUDYMATE_STORAGE", "local")
    print(f"Storage mode: {mode}")
    try:
        store = get_store()
        docs = store.list_documents()
        ok(f"Storage reachable: {store.description} ({len(docs)} document(s))")
    except StorageError as exc:
        bad(str(exc)); problems += 1

    if mode == "s3" or "--invoke" in sys.argv:
        try:
            import boto3
            ident = boto3.client("sts", region_name=os.getenv("AWS_REGION") or None).get_caller_identity()
            ok(f"AWS credentials work (account {ident['Account']})")
        except Exception as exc:
            bad(friendly_aws_message(exc) or str(exc)); problems += 1

    if "--invoke" in sys.argv:
        from agent import AgentCallError, ask_baseline, build_baseline_agent
        try:
            reply = ask_baseline(build_baseline_agent(), "Reply with the single word: OK")
            ok(f"Bedrock model replied: {reply[:60]!r}")
        except AgentCallError as exc:
            bad(str(exc)); problems += 1
    else:
        print("(Skipped the Bedrock model test. Add --invoke to run it.)")
    print("\nAll checks passed." if not problems else f"\n{problems} problem(s) found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
