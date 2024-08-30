# Minimum code for enabling editable install

from setuptools import find_packages, setup

setup(
    name="rightconf",
    packages=find_packages(),
    install_requires=["omegaconf"],
)
