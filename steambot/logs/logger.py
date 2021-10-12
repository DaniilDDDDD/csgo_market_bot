import logging
import pathlib

basedir = pathlib.Path(__file__).parent.parent.absolute()

logger = logging.getLogger('core.main')
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(f'{basedir}/logs/main_logs.log', mode='w')
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.info('Program started!')


def log(out: str, level: str = 'INFO'):
    if level == 'INFO':
        logger.info(str(out))
    elif level == 'WARNING':
        logger.warning(str(out))
    elif level == 'ERROR':
        logger.error(str(out))
    elif level == 'CRITICAL':
        logger.critical(str(out))
    print(f'{level}: {str(out)}')
