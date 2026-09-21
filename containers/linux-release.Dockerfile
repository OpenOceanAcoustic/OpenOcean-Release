FROM quay.io/pypa/manylinux_2_28_x86_64@sha256:d5f19b5957cf25df7ac15465924cafe2358754a187e510af386bf9596598a372

RUN dnf install -y eigen3-devel git ninja-build ccache tar gzip zip unzip \
    && dnf clean all

# The image deliberately keeps cibuildwheel's CPython 3.10-3.14 matrix in
# /opt/python. Python build dependencies are pinned and cached by main.py.
ENV CMAKE_BUILD_PARALLEL_LEVEL=2
