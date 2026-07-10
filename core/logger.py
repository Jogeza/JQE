import logging
from pathlib import Path


Path("logs").mkdir(exist_ok=True)


logging.basicConfig(

    filename="logs/jqe.log",

    level=logging.INFO,

    format="%(asctime)s | %(levelname)s | %(message)s"

)


logger = logging.getLogger("JQE")