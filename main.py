from core.mt5_connection import (
    connect,
    disconnect
)

from core.logger import logger



def main():

    logger.info(
        "JQE Engine Started"
    )


    if connect():

        print(
            "JQE ENGINE ONLINE"
        )


    disconnect()



if __name__ == "__main__":

    main()