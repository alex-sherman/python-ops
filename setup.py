#!/usr/bin/env python

from distutils.core import setup

setup(
  name = "ops",
  version = "0.0.2",
  description = "A Python devops utility",
  scripts = ["ops"],
  py_modules = ["ops"],
  install_requires=['pyyaml'],
  author='Alex Sherman',
  author_email='asherman1024@gmail.com',
  url='https://github.com/alex-sherman/python-ops')
