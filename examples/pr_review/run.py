"""Run the pr_review workflow."""
from graph import run_workflow


def main():
    result = run_workflow(
        pr_url="https://github.com/owner/repo/pull/1",
    )
    print(f"Verdict: {result.get('verdict')}")
    print(f"Summary: {result.get('review_summary')}")


if __name__ == "__main__":
    main()
