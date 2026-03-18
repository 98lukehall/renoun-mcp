# ReNoUn Risk Gate for Freqtrade

Structural regime filter for Freqtrade. Checks market conditions before every trade.

## The Stoplight

| Regime | Action | What Happens |
|--------|--------|-------------|
| Bounded (green) | proceed | Full position size |
| Active (yellow) | reduce | Position scaled by exposure scalar |
| Unstable (red) | avoid | Trade blocked |

## Setup

### 1. Get a free API key

```bash
curl -X POST https://web-production-817e2.up.railway.app/v1/keys/provision \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "agent_name": "freqtrade"}'
```

### 2. Add to config.json

```json
{
  "renoun_api_key": "rn_agent_YOUR_KEY"
}
```

### 3. Install

```bash
cp ReNoUnRiskGate.py /path/to/freqtrade/user_data/strategies/
```

### 4. Run

```bash
freqtrade trade --strategy ReNoUnRiskGate
```

## Use With Your Own Strategy

The risk gate works as a mixin. Subclass it and override the entry/exit logic:

```python
from ReNoUnRiskGate import ReNoUnRiskGate

class MyStrategy(ReNoUnRiskGate):
    """Your entry logic + ReNoUn risk gate."""

    def populate_entry_trend(self, dataframe, metadata):
        # Your entry logic here
        ...
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        # Your exit logic here
        ...
        return dataframe
```

The `confirm_trade_entry`, `custom_stake_amount`, and `custom_exit` callbacks are inherited automatically.

## What It Does

Before every trade:
1. Calls `GET /v1/regime/live/{symbol}` (cached 60s)
2. If **unstable** → blocks the trade
3. If **active** with low exposure → blocks the trade
4. If **exit_now** urgency → blocks new entry
5. If **active** → scales position by exposure scalar
6. If **bounded** → full position, normal entry

During a trade:
- If regime shifts to unstable with `exit_now` urgency → forces exit

## Configuration

Set these in your strategy class:

| Setting | Default | Description |
|---------|---------|-------------|
| `renoun_block_unstable` | True | Block trades when regime is unstable |
| `renoun_scale_active` | True | Scale position by exposure scalar |
| `renoun_min_exposure` | 0.3 | Skip trade if exposure below this |
| `renoun_honor_exit_urgency` | True | Force exit on exit_now signal |

## Costs

- 50 free API calls/day (one call per trade check, cached 60s)
- $0.02/call beyond free tier
- A typical Freqtrade bot checking 5 pairs every minute uses ~7,200 calls/day

## Links

- [ReNoUn Dashboard](https://harrisoncollab.com/dashboard)
- [API Docs](https://harrisoncollab.com/agents)
- [Live Signals on X](https://x.com/98lukehall)
