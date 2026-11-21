#!/bin/bash
# Full end-to-end demo run (Groq route). Tee output to the transcript file.
cd ~/workspace/dorahacks-cortensor-2418 || exit 1
NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
  .venv/bin/python -u -m triage_agent.cli --fresh --pace 25 2>&1 | tee docs/demo-transcript.txt
echo "DEMO EXIT: ${PIPESTATUS[0]}"
