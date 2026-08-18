import importlib

import crypto_loader

crypto_loader.install()

run = importlib.import_module("app").run

if __name__ == "__main__":
    run()
