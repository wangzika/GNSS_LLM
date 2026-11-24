#!/usr/bin/env bash
# 在已授权的 GPU 服务器上启动本地教师模型 API。
# 模型、环境、缓存和临时文件均放在 /data/zbwang。
set -euo pipefail

teacher_root=/data/zbwang
teacher_python_env="$teacher_root/envs/gnss-teacher-vllm"
teacher_model="$teacher_root/models/Qwen2.5-32B-Instruct"
teacher_headers="$teacher_root/build/Python-3.10.16"

if [[ ! -f "$teacher_model/.download_complete" ]]; then
  echo "模型尚未完成下载和文件校验：$teacher_model" >&2
  exit 1
fi
if [[ ! -x "$teacher_python_env/bin/vllm" ]]; then
  echo "缺少 vLLM：$teacher_python_env/bin/vllm" >&2
  exit 1
fi
if [[ ! -f "$teacher_headers/Include/Python.h" || ! -f "$teacher_headers/pyconfig.h" ]]; then
  echo "缺少 Python 3.10 编译头文件：$teacher_headers" >&2
  exit 1
fi

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1,2}"
export HF_HOME="$teacher_root/cache/huggingface"
export XDG_CACHE_HOME="$teacher_root/cache/xdg"
export VLLM_CACHE_ROOT="$teacher_root/cache/vllm"
export TRITON_CACHE_DIR="$teacher_root/cache/triton"
export TORCHINDUCTOR_CACHE_DIR="$teacher_root/cache/torchinductor"
export TMPDIR="$teacher_root/tmp"
# 服务器只安装了 Python 3.10 运行时；Triton 编译时需匹配版本的头文件。
export CPATH="$teacher_headers/Include:$teacher_headers${CPATH:+:$CPATH}"
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$VLLM_CACHE_ROOT" \
  "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$TMPDIR"

exec "$teacher_python_env/bin/vllm" serve "$teacher_model" \
  --served-model-name Qwen/Qwen2.5-32B-Instruct \
  --tensor-parallel-size 2 \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --host 127.0.0.1 \
  --port 8000
