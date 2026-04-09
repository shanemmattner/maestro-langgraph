"""Run the adaptive workflow."""
from graph import build_graph


def main():
    graph = build_graph()
    result = graph.invoke({"task": "Your task here"})
    print(result.get("summary", "Done"))


if __name__ == "__main__":
    main()
