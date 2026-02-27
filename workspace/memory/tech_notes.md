# Technical Notes & Benchmarks

## Qwen 3.5-35B-A3B (MoE)
*Source: User PSA (Feb 2026)*
- **Status:** Not supported in standard Ollama/LM Studio yet.
- **Workaround:** `llama.cpp` built from source + Unsloth GGUF (Q4_K_XL).
- **Performance (M4 Max):** 60.5 tok/s (gen), 136.7 tok/s (prompt).
- **VRAM:** ~19.6GB.
- **Issues:**
  - Thinking mode crashes (`llama.cpp #19869`) -> **MUST DISABLE**.
  - Vulkan backend broken -> Use Metal.
  - Tool calling template issues.

## Current Setup (Qwen 3.0)
- We are running `ollama/qwen3:30b-a3b`.
- **Action:** Ensure `thinking="off"` is set in all agent scripts to prevent similar MoE crashes.
- 2026-02-26: Created ops/lab_setup.sh for Qwen 3.5 MoE (llama.cpp source build). Requires manual trigger to download 18GB model.
