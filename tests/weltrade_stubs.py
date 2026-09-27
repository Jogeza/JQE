"""Offline Weltrade-shaped gateway fixtures; never connect to the terminal.

The fixed one-unit price economics are a test assumption, not a contract spec.
Production factory/configuration is never patched to accept another broker.
"""
from broker.simulation_gateway import SimulationGateway
from broker.types import AccountInfo, ExecutionQuantity, ExecutionQuantityUnit


class WeltradeStubGateway(SimulationGateway):
    async def get_account_info(self):
        account = await super().get_account_info()
        return account.model_copy(update={
            "account_id": "4242", "server": "Weltrade-Demo", "trade_mode": "demo",
        })

    async def authorize_account_currency_risk(self, *, balance, risk_percent, entry, stop_loss, **kwargs):
        risk = balance * risk_percent / 100
        quantity = risk / abs(entry - stop_loss)
        return ExecutionQuantity(value=quantity, unit=ExecutionQuantityUnit.MT5_LOTS), {
            "authorized_risk_amount": risk, "expected_loss_at_stop": risk,
        }

    async def submit_order(self, order):
        assert order.quantity.unit is ExecutionQuantityUnit.MT5_LOTS
        internal_order = order.model_copy(update={"quantity": ExecutionQuantity(
            value=order.quantity.value, unit=ExecutionQuantityUnit.SIMULATION_UNITS,
        )})
        return self._fill_order(internal_order, order.entry_price or 101.0)
