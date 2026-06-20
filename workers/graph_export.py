"""gbrain · export the knowledge graph for the viewer.

Dumps gb_graph_json() to graph.json next to graph_viewer.html.
  python -m workers.graph_export [output_path]
"""

from __future__ import annotations

import json
import sys

from workers.lib.db import connect


def main(out: str = "graph.json") -> None:
    conn = connect()
    data = conn.execute("select gb_graph_json() as g").fetchone()["g"]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, default=str)
    print(f"wrote {out}: {len(data.get('nodes', []))} nodes, "
          f"{len(data.get('edges', []))} edges")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "graph.json")
