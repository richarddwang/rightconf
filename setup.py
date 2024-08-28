# Minimum code for enabling editable install

from setuptools import setup, find_packages
  
setup(  
    name='rightconf',  
    packages=find_packages(),
    requires=['omegaconf']
)