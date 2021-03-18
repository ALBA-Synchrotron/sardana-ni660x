import sys
from setuptools import setup, find_packages


def main():
    """Main method collecting all the parameters to setup."""
    name = "sardana-ni660x"
    _version = "0.1.0"
    description = "NI660X Sardana Controller"
    author = "ALBA controls team"
    author_email = "controls@cells.es"
    license = "GPLv3"
    url = "http://github.com/ALBA-Synchrotron/sardana-ni660x"
    packages = find_packages()

    # Add your dependencies in the following line.
    install_requires = ['sardana']

    python_requires = '>=3.5'

    setup(
        name=name,
        version=_version,
        description=description,
        author=author,
        author_email=author_email,
        license=license,
        url=url,
        packages=packages,
        install_requires=install_requires,
        python_requires=python_requires,
    )

if __name__ == "__main__":
    main()
