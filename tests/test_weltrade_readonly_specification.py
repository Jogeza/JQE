import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from broker.weltrade_gateway import WeltradeGateway
from core.exceptions import BrokerConnectionError


@pytest.mark.asyncio
async def test_specification_reads_exact_symbol_off_loop_without_selection():
    gateway=WeltradeGateway.__new__(WeltradeGateway)
    main_thread=threading.get_ident()
    def info(symbol):
        assert threading.get_ident()!=main_thread
        assert symbol=="SFX Vol 99"
        return SimpleNamespace(name=symbol,digits=2,visible=False)
    with patch.object(gateway,"_require_connected"),patch("broker.weltrade_gateway.mt5.symbol_info",side_effect=info), \
         patch.object(gateway,"_resolve_symbol",side_effect=AssertionError("Observation must not select")):
        result=await gateway.get_symbol_specification("SFX Vol 99")
    assert result["name"]=="SFX Vol 99"


@pytest.mark.asyncio
async def test_missing_exact_contract_is_not_replaced_with_alias():
    gateway=WeltradeGateway.__new__(WeltradeGateway)
    with patch.object(gateway,"_require_connected"),patch("broker.weltrade_gateway.mt5.symbol_info",return_value=None):
        with pytest.raises(BrokerConnectionError,match="specification is unavailable"):
            await gateway.get_symbol_specification("SFX Vol 99")
