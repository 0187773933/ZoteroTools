#!/bin/bash
python3 -m venv qwenpdf
source qwenpdf/bin/activate
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install transformers accelerate pillow pymupdf tqdm requests
pip install qwen-vl-utils
