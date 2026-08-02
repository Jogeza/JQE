import MetaTrader5 as mt5


def test_mt5_connection():
    connected = mt5.initialize()

    assert connected is True, "MT5 connection failed"

    account = mt5.account_info()

    assert account is not None

    print(account)

    mt5.shutdown()