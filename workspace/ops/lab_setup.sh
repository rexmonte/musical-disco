#!/bin/zsh
# ops/lab_setup.sh - Experimental Qwen 3.5 MoE Setup
# WARNING: Downloads ~20GB and compiles code.

set -e

WORK_DIR="$HOME/.openclaw/workspace/lab/qwen3.5"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

echo "🧪 Starting Lab Setup for Qwen 3.5-35B-A3B..."

# 1. Install Dependencies
if ! command -v cmake &> /dev/null; then
    echo "Installing cmake..."
    brew install cmake
fi

# 2. Clone llama.cpp (Bleeding Edge)
if [ ! -d "llama.cpp" ]; then
    echo "Cloning llama.cpp..."
    git clone https://github.com/ggerganov/llama.cpp
fi

cd llama.cpp

# 3. Build with Metal (M4 Optimization)
echo "Building llama.cpp with Metal support..."
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release -j$(sysctl -n hw.logicalcpu)

# 4. Download Model (Unsloth GGUF Q4_K_XL - 18GB)
MODEL_URL="https://huggingface.co/unsloth/Qwen2.5-35B-A3B-Instruct-GGUF/resolve/main/Qwen2.5-35B-A3B-Instruct-Q4_K_XL.gguf"
MODEL_FILE="../Qwen2.5-35B-A3B-Instruct-Q4_K_XL.gguf"

if [ ! -f "$MODEL_FILE" ]; then
    echo "Downloading 18GB Model (This takes time)..."
    curl -L "$MODEL_URL" -o "$MODEL_FILE"
else
    echo "Model already downloaded."
fi

echo "✅ Setup Complete."
echo "To run server:"
echo "./build/bin/llama-server -m $MODEL_FILE -c 8192 --port 8081 --n-gpu-layers 99"
