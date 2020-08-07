import os
import sys

path = os.path.dirname(os.path.realpath(__file__)) + os.sep + ".."
sys.path.insert(0, path)

path = os.path.dirname(os.path.realpath(__file__))
os.chdir(path)