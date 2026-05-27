"""Phase 1 smoke test: build a tree from a hardcoded paragraph and print it.

Requires OPENAI_API_KEY in the environment (or backend/.env).

    cd backend && python -m scripts.sample_build
"""
import json
import os
import sys

from dotenv import load_dotenv

# Load backend/.env if present
load_dotenv()

from app.serialization import serialize_tree  # noqa: E402

SAMPLE_TEXT = (
    "The Apollo program was a series of human spaceflight missions undertaken by NASA "
    "between 1961 and 1972. Its goal was to land humans on the Moon and bring them "
    "safely back to Earth. Apollo 11, in July 1969, achieved that goal when Neil "
    "Armstrong and Buzz Aldrin walked on the lunar surface while Michael Collins "
    "orbited above. Five more crewed landings followed through Apollo 17. The program "
    "produced lasting advances in rocketry, computing, and materials science. It also "
    "returned 382 kilograms of lunar samples that continue to inform planetary "
    "geology today. Public interest waned after the initial landing, and budget "
    "pressure led to the cancellation of Apollos 18 through 20."
)


def main() -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set. Copy backend/.env.example to .env.", file=sys.stderr)
        return 1

    from raptor import RetrievalAugmentation, RetrievalAugmentationConfig

    # Small chunks so a multi-layer tree forms from a short paragraph.
    config = RetrievalAugmentationConfig(tb_max_tokens=40, tb_num_layers=3)
    ra = RetrievalAugmentation(config=config)
    ra.add_documents(SAMPLE_TEXT)

    serialized = serialize_tree(ra.tree)
    print(json.dumps(serialized, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
