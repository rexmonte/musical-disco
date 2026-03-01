# Recent Changes (via Claude Code)

## 2026-03-01
- Ollama: Bumped context to 48K with Q8_0 KV cache quantization (~2.4x more conversation history)
- OpenClaw: bootstrapTotalMaxChars 8K->16K, reserveTokensFloor 4096->6144
- PolyMaker: Fixed ask side -- BUY NO token instead of SELL YES. Bot live.
- Compaction: Patched Ollama->Haiku fallback for summarization (Ollama has no pi-ai provider)
