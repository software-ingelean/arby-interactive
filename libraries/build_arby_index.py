"""Build Arby's FAISS index once, and rebuild after editing the Markdown."""
import argparse
from pathlib import Path
from arby_knowledge import build_index, DEFAULT_EMBEDDING_MODEL


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, default=base / "contexto_arby.md")
    parser.add_argument("--index", type=Path, default=base / "faiss_index")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    args = parser.parse_args()
    result = build_index(args.context, args.index, embedding_model=args.embedding_model)
    print(f"Índice generado: {result['chunks']} fragmentos, {result['workers']} trabajadores.")
    print(result['path'])


if __name__ == "__main__":
    main()
