
# create a service file
sudo nano /etc/systemd/system/vllm.service

```
[Unit]
Description=vLLM Inference Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu

WorkingDirectory=/data/ai

Environment="HF_HOME=/data/ai/hf-cache"
EnvironmentFile=/etc/vllm/environment

ExecStart=/data/ai/environments/vllm/bin/vllm serve \
    Qwen/Qwen3-Coder-30B-A3B-Instruct \
    --served-model-name coding-assistant \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching

Restart=always
RestartSec=10

TimeoutStartSec=900
TimeoutStopSec=120

LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
```

after this create hf token param

```
sudo mkdir -p /data/vllm

sudo vi /data/vllm/environment
```

update environment file with
```
HF_TOKEN=hf_xxxxx
```

then
```
sudo chmod 600 /data/vllm/environment

sudo systemctl daemon-reload
sudo systemctl enable vllm
sudo systemctl start vllm
sudo systemctl status vllm
# check logs
journalctl -u vllm -f
# validate
curl http://localhost:8000/v1/models
```