#!/usr/bin/env bash
# Training command on host GPU (RTX 5060 Ti 16GB):
yolo detect train data=/home/tieubaoca/AI/AI-Camera-OC/data/mixed_traffic/dataset.yaml model=yolo26s.pt epochs=50 imgsz=640 batch=16 device=0
# Export to ONNX NMS-free:
yolo export model=runs/detect/train/weights/best.pt format=onnx imgsz=640 nms=True
