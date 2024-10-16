#!/bin/bash

mongod --dbpath /data/db --fork --logpath /var/log/mongod.log

cd /root/data/mev/arbitrage/arbitrum
python3 import_arbitrum_arbitrage.py
cd /root/data/mev/arbitrage/ethereum
python3 import_ethereum_arbitrage.py
cd /root/data/mev/arbitrage/optimism
python3 import_optimism_arbitrage.py
cd /root/data/mev/arbitrage/zksync
python3 import_zksync_arbitrage.py

cd /root/data/mev/liquidation/arbitrum
python3 import_arbitrum_liquidations.py
cd /root/data/mev/liquidation/ethereum
python3 import_ethereum_liquidations.py
cd /root/data/mev/liquidation/optimism
python3 import_optimism_liquidations.py
cd /root/data/mev/liquidation/zksync
python3 import_zksync_liquidations.py

cd /root/data/mev/sandwiching/ethereum
python3 import_ethereum_sandwiches.py

cd /root/data/mev/opportunities/arbitrage/arbitrum
python3 import_arbitrum_arbitrage_opportunities.py
cd /root/data/mev/opportunities/arbitrage/ethereum
python3 import_ethereum_arbitrage_opportunities.py
cd /root/data/mev/opportunities/arbitrage/optimism
python3 import_optimism_arbitrage_opportunities.py
cd /root/data/mev/opportunities/arbitrage/zksync
python3 import_zksync_arbitrage_opportunities.py

cd /root/data/mev/opportunities/liquidation/arbitrum
python3 import_arbitrum_liquidation_opportunities.py
cd /root/data/mev/opportunities/liquidation/ethereum
python3 import_ethereum_liquidation_opportunities.py
cd /root/data/mev/opportunities/liquidation/optimism
python3 import_optimism_liquidation_opportunities.py
cd /root/data/mev/opportunities/liquidation/zksync
python3 import_zksync_liquidation_opportunities.py

cd /root/data/cross_layer_sandwiching/l1_transactions
python3 import_l1_messages.py

cd /root/data/cross_layer_sandwiching/l2_transactions/arbitrum
python3 import_arbitrum_l2_messages.py
cd /root/data/cross_layer_sandwiching/l2_transactions/optimism
python3 import_optimism_l2_messages.py

cd /root/data/cross_layer_sandwiching/sandwich_simulation/arbitrum
python3 import_arbitrum_sandwich_simulation.py
cd /root/data/cross_layer_sandwiching/sandwich_simulation/optimism
python3 import_optimism_sandwich_simulation.py

cd /root/analysis
jupyter notebook --port=8888 --no-browser --ip=0.0.0.0 --allow-root --NotebookApp.token='' --NotebookApp.password='' & disown

/bin/bash "$@"
