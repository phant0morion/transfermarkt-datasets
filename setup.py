#!/usr/bin/env python3
"""
Simple setup.py for Streamlit Cloud compatibility
"""

from setuptools import setup, find_packages

with open("requirements.txt", "r", encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="transfermarkt-datasets",
    version="0.1.0",
    description="Extract, prepare, publish and update Transfermarkt datasets.",
    author="dcaribou",
    author_email="davidcereijo@live.com",
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.8.1,<3.14",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)
