"""Run the chain_of_thought workflow."""
from graph import build_graph


def main():
    graph = build_graph()
    result = graph.invoke({
        "question": "Your question here",
        "context": "none",
        "domain": "general",
        "sub_questions": [],
        "assumptions": [],
        "reasoning_steps": [],
        "step_errors": [],
    })
    print(result.get("answer", "Done"))


if __name__ == "__main__":
    main()
