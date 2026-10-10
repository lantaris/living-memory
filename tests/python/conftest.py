# The prototype scenario scripts are exercised as subprocesses through
# test_prototype_suite.py; collect them directly would import them in-process.
collect_ignore_glob = ["prototype/*"]
