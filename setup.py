from setuptools import setup

setup(
    name='jupyterhub-winlocalprocessspawner',
    version='1.0',
    description='Windows Local Process Spawner for JupyterHub',
    url='https://github.com/ni/jupyterhub-winlocalprocessspawner',
    author='Alejandro del Castillo',
    license='MIT',
    packages=['winlocalprocessspawner'],
    install_requires=[
        'pywin32',
        'jupyterhub',
    ]
)
