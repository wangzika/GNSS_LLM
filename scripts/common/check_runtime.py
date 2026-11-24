#!/usr/bin/env python3
"""Check the active Conda environment and Blackwell CUDA usability."""
import os
import sys


def main():
    print(f"Python: {sys.version.split()[0]}")
    print(f"Conda: {os.environ.get('CONDA_DEFAULT_ENV', '通过环境 Python 直接执行')}; prefix: {sys.prefix}")
    try:
        import torch
    except ImportError as exc:
        raise SystemExit(f"PyTorch 未安装: {exc}")
    print(f"PyTorch: {torch.__version__}; CUDA build: {torch.version.cuda}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA 不可用；请检查宿主 NVIDIA 驱动及当前执行权限")
    print(f"GPU: {torch.cuda.get_device_name(0)}; capability: {torch.cuda.get_device_capability(0)}")
    x = torch.tensor([1.0], device="cuda")
    print(f"GPU kernel: {(x + 1).item()}")


if __name__ == "__main__":
    main()
