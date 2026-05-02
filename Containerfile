#
# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===
#

FROM docker.io/library/python:3.13-slim

# Install Python dependencies once into the image.
# The application source code is mounted at runtime by Quadlet.
WORKDIR /opt/app

COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

