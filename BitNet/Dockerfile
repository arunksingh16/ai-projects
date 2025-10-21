FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)"
RUN apt update && \
    apt install -y python3-pip cmake clang git wget vim curl bash libgl1-mesa-glx libegl1-mesa libxrandr2 libxrandr2 libxss1 libxcursor1 libxcomposite1 libasound2 libxi6 libxtst6 && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --recursive https://github.com/microsoft/BitNet.git
# INSTALL PIP
WORKDIR /BitNet
RUN pip install -r requirements.txt && \
    pip cache purge
RUN pip install sentencepiece
RUN pip install -U "huggingface_hub[cli]"
RUN huggingface-cli download microsoft/BitNet-b1.58-2B-4T-gguf --local-dir models/BitNet-b1.58-2B-4T
RUN python3 setup_env.py -md models/BitNet-b1.58-2B-4T -q i2_s
# RUN python3 run_inference.py -m models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf -p "You are a helpful assistant. Always follow the user's instructions." -cnv
