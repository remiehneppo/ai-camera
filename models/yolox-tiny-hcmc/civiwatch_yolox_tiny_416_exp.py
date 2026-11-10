#!/usr/bin/env python3
import os
from yolox.exp import Exp as MyExp


class Exp(MyExp):
    def __init__(self):
        super().__init__()
        self.depth = 0.33
        self.width = 0.375
        self.input_size = (416, 416)
        self.test_size = (416, 416)
        self.multiscale_range = 0
        self.num_classes = 6
        self.data_dir = r"/home/tieubaoca/AI/AI-Camera-OC/data/mixed_traffic_coco"
        self.train_ann = "instances_train2017.json"
        self.val_ann = "instances_val2017.json"
        self.output_dir = r"/home/tieubaoca/AI/AI-Camera-OC/data/YOLOX_outputs"
        self.max_epoch = 10
        self.warmup_epochs = 1
        self.no_aug_epochs = 2
        self.enable_mixup = False
        self.basic_lr_per_img = 0.005 / 64.0
        self.data_num_workers = 6
        self.eval_interval = 2
        self.save_history_ckpt = False
        self.exp_name = "civiwatch_yolox_tiny_416"
