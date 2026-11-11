nvidia-smi

nvcc --version

which python3
python3 --version

ls -l /usr/local/cuda*

nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv

sudo mkdir -p /data/ai/{environments,models,hf-cache,logs}
sudo chown -R ubuntu:ubuntu /data/ai
cd /data/ai/environments

uv venv vllm --python 3.12

source /data/ai/environments/vllm/bin/activate


# Native vLLM installation
uv venv vllm --python 3.12

source /data/ai/environments/vllm/bin/activate

uv pip install vllm --torch-backend=auto

vllm download-kernels

# verify
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.get_device_name(0))"

python -c "import vllm; print(vllm.__version__)"

python -c "
import torch
print('CUDA available:', torch.cuda.is_available())
print('GPU:', torch.cuda.get_device_name(0))
print('VRAM:', round(torch.cuda.get_device_properties(0).total_memory/1024**3,2), 'GB')
"