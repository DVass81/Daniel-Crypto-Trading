from crypto_bot.bot import run_forever
from crypto_bot.config import load_config


if __name__ == "__main__":
    run_forever(load_config())
