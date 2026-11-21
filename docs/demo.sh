#!/bin/bash
# Short, video-recordable demo: first 3 findings, Ollama-free Groq route.
# Output is plain terminal text, no interaction needed; record with any
# terminal recorder (e.g. `asciinema rec` or screen capture) for 1-5 min.
# Usage: bash docs/demo.sh   (from the repo root; venv + GROQ_API_KEY set)
set -e
cd "$(dirname "$0")/.."
export NO_PROXY=localhost,127.0.0.1
export no_proxy=localhost,127.0.0.1
.venv/bin/python -u -m triage_agent.cli --fresh --limit 3 --pace 10
