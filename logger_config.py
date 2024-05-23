from loguru import logger
import sys

def setup_logger():
    logger.remove()
    log_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"

    # Configure logger to print to stdout
    logger.add(sys.stdout, format=log_format, level="DEBUG")

# Call the setup function to ensure the logger is configured when imported
setup_logger()