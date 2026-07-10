"""
JQE Data Validator

Checks market data quality before analysis.
"""


import pandas as pd

from core.logger import logger



def validate_market_data(df):

    """
    Validate OHLC market data.
    """


    if df is None:

        logger.error(
            "No market data received"
        )

        return False



    if df.empty:

        logger.error(
            "Empty dataframe"
        )

        return False



    required_columns = [

        "time",
        "open",
        "high",
        "low",
        "close"

    ]



    for column in required_columns:

        if column not in df.columns:

            logger.error(
                f"Missing column: {column}"
            )

            return False



    # Check duplicates

    duplicates = df.duplicated(
        subset=["time"]
    ).sum()



    if duplicates > 0:

        logger.warning(
            f"Removing {duplicates} duplicate candles"
        )

        df.drop_duplicates(
            subset=["time"],
            inplace=True
        )



    # Check invalid candles

    invalid = df[
        (df["high"] < df["low"]) |
        (df["close"] > df["high"]) |
        (df["close"] < df["low"])
    ]



    if len(invalid) > 0:

        logger.error(
            "Invalid OHLC candles detected"
        )

        return False



    logger.info(
        "Market data validation successful"
    )


    return True