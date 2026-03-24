FROM vllm/vllm-openai:latest

# MiroFish vLLM Inference Server
# Serves open models (Qwen2.5-72B, DeepSeek-V3, Llama3-70B) via OpenAI-compatible API
# Deploy on Vast.ai, RunPod, Lambda, or any GPU cloud

ENV MODEL_NAME="Qwen/Qwen2.5-72B-Instruct"
ENV TENSOR_PARALLEL_SIZE=2
ENV MAX_MODEL_LEN=4096
ENV GPU_MEMORY_UTILIZATION=0.92
ENV PORT=8000
ENV MAX_NUM_SEQS=256

# Pre-install useful extras
RUN pip install --no-cache-dir requests

EXPOSE ${PORT}

# vLLM OpenAI-compatible server
CMD python -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_NAME} \
    --tensor-parallel-size ${TENSOR_PARALLEL_SIZE} \
    --max-model-len ${MAX_MODEL_LEN} \
    --gpu-memory-utilization ${GPU_MEMORY_UTILIZATION} \
    --port ${PORT} \
    --max-num-seqs ${MAX_NUM_SEQS} \
    --trust-remote-code \
    --enable-prefix-caching
