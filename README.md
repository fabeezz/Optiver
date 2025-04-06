# 📈 Competitive Trader Bot for Optibook

This project implements a competitive trading bot for use with the Optibook trading simulation platform. The bot identifies arbitrage opportunities between two synthetic instruments (`PHILIPS_A` and `PHILIPS_B`) and executes hedged trades, all while respecting position, hedge, and update rate constraints.

## 🚀 Features

- 📊 **Arbitrage Detection**: Scans the order books for profitable mismatches between the two instruments.
- 🛡️ **Hedge Compliance**: Ensures the sum of positions is within the allowed hedge band (±40). Automatic correction is triggered after a 3-second grace period if the hedge is violated.
- ⚡ **Rate Limiting**: Enforces an update rate of no more than 25 orders per second to comply with platform restrictions.
- 📈 **Position Limits**: Prevents trades that would exceed the position limit (±200).
- 🤖 **Fully Automated Trading Loop**: Continuously monitors the market and executes trades when opportunities are found.

## 🧠 Trading Logic Overview

1. **Find Opportunities**:
   - If `PHILIPS_A` is overpriced relative to `PHILIPS_B`, the bot sells A and buys B.
   - If `PHILIPS_B` is overpriced relative to `PHILIPS_A`, the bot sells B and buys A.
   - Only trades when profit is guaranteed and hedge constraints allow.

2. **Execute Hedged Trade**:
   - Trades are executed as immediate-or-cancel (IOC) to avoid lingering orders.
   - The bot always hedges immediately to maintain market neutrality.

3. **Maintain Hedge**:
   - If combined position (A + B) is outside of `[-40, 40]` for more than 3 seconds, corrective trades are triggered to rebalance.

## 📣 Notes

- Designed for high-frequency, low-latency trading simulations.
- Conservative risk management: trades are skipped if they would breach constraints instead of queueing or delaying.
