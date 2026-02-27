# Polymarket Market Maker Bot

A production-ready market making bot for Polymarket's 5-minute and 15-minute BTC/ETH/SOL markets.

## Features

- Market discovery for active crypto markets
- Real-time orderbook monitoring via WebSocket
- Market making with configurable spreads
- Inventory management and risk controls
- Paper trading mode for testing
- Graceful shutdown handling

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Create a `.env` file based on `.env.example`:
   ```
   PRIVATE_KEY=your_private_key_here
   MAX_EXPOSURE_USD=500
   MAX_TOTAL_EXPOSURE_USD=2000
   SPREAD_BPS=200
   INVENTORY_SKEW_THRESHOLD=0.35
   LOG_ONLY=false
   ```

3. Run the bot:
   ```
   python bot.py
   ```

## Paper Trading Mode

Set `LOG_ONLY=true` in your `.env` file to enable paper trading mode. In this mode, the bot will:
- Log all actions it would take
- NOT place actual orders
- Allow you to test strategies without risking real funds

## Components

1. **gamma_client.py** - Market discovery using Gamma API
2. **orderbook.py** - Orderbook monitoring via WebSocket
3. **market_maker.py** - Core market making logic
4. **risk.py** - Risk controls and exposure management
5. **bot.py** - Main runner orchestrating all components

## Risk Controls

- Maximum exposure per market: $500
- Maximum total exposure across all markets: $2000
- Maximum inventory skew: 35% (one-sided position)
- Emergency stop if drawdown exceeds 10% of capital