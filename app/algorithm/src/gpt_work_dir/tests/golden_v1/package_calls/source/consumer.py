import pkg


def run():
    pkg.outer(pkg.inner())
    pkg.outer()
    pkg.outer()
