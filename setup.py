from setuptools import setup, find_packages

setup(
    name="istio_config_parser",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'flask',
        'flask-cors',
    ],
) 