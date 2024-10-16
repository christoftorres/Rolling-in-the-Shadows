<h1 align="center">Rolling in the Shadows</h1>

This repository contains our dataset of detected MEV across Ethereum and layer-2 rollups such as Arbitrum, Optimism, and zkSync. It also includes a collection of tools that we used to measure and compare MEV as well as a proof-of-concept implementation of cross-layer sandwich attacks where we demonstrate that frontrunning is possible on layer-2 rollups as a normal user (i.e., without being a sequencer). 

Our paper can be found [here](https://arxiv.org/pdf/2405.00138).

## Quick start

A container with all the dependencies can be found [here](https://hub.docker.com/r/christoftorres/rolling-in-the-shadows/).

To run the container, please install docker and run:

:warning: Please make sure that you have cloned this repository beforehand and that your current working directory is the root folder of this repository. Alternatively change the path ```-v ./:/root``` below. This is because the container will first try to import all the data into an instance of MongoDB when started. Please keep in mind that this process might take a while, so feel free to grab a cup of coffee meanwhile. :warning:

``` shell
docker pull christoftorres/rolling-in-the-shadows && docker run -m 16g --memory-swap="24g" -p 8888:8888 -v ./:/root -it christoftorres/rolling-in-the-shadows:latest
```

After starting the container it will import all the collected data into an instance of MongoDB running inside the container and finally launch a jupyter notebook server. 

## Custom Docker image build

``` shell
docker build -t rolling-in-the-shadows .
docker run -m 16g --memory-swap="24g" -p 8888:8888 -v ./:/root -it rolling-in-the-shadows:latest
```

## Installation instructions

### 1. Install MongoDB

##### MacOS

``` shell
brew tap mongodb/brew
brew install mongodb-community@6.0.4
```

##### Ubuntu

``` shell
curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/6.0 multiverse" | tee /etc/apt/sources.list.d/mongodb-org-6.0.list
apt-get update
apt-get install mongodb-org=6.0.4 mongodb-org-database=6.0.4 mongodb-org-server=6.0.4 mongodb-org-mongos=6.0.4 mongodb-org-tools=6.0.4
```

For other operating systems follow the installation instructions on [mongodb.com](https://docs.mongodb.com/manual/installation/).

### 2. Install Python dependencies

``` shell
python3 -m pip install -r requirements.txt
```

## Measuring MEV extraction in the wild

Make sure MongoDB is running and that you have installed all Python dependencies.

:warning: To measure past MEV extraction you will need a connection to a fully synched archive node and change ```PROVIDER``` in ```scripts/utils/settings.py``` accordingly. :warning:

### Downloading Flashbots data for Ethereum

``` shell
cd scripts/mev/flashbots
python3 download_falshbots_data.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

### Measuring arbitrage

``` shell
cd scripts/mev/arbitrage/ethereum
python3 arbitrage.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/arbitrage/arbitrum
python3 arbitrage.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/arbitrage/optimism
python3 arbitrage.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/arbitrage/zksync
python3 arbitrage.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

### Measuring liquidation

``` shell
cd scripts/mev/liquidation/ethereum
python3 liquidation.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/liquidation/arbitrum
python3 liquidation.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/liquidation/optimism
python3 liquidation.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/liquidation/zksync
python3 liquidation.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

### Measuring sandwiching

``` shell
cd scripts/mev/sandwiching/ethereum
python3 sandwiching.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/sandwiching/arbitrum
python3 sandwiching.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/sandwiching/optimism
python3 sandwiching.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

``` shell
cd scripts/mev/sandwiching/zksync
python3 sandwiching.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

### Measuring opportunities

#### Arbitrage

``` shell
cd scripts/mev/opportunities/arbitrage/ethereum
python3 opportunity.py
```

``` shell
cd scripts/mev/opportunities/arbitrage/arbitrum
python3 opportunity.py
```

``` shell
cd scripts/mev/opportunities/arbitrage/optimism
python3 opportunity.py
```

``` shell
cd scripts/mev/opportunities/arbitrage/zksync
python3 opportunity.py
```

#### Liquidation

``` shell
cd scripts/mev/opportunities/liquidation/ethereum
python3 opportunity.py
```

``` shell
cd scripts/mev/opportunities/liquidation/arbitrum
python3 opportunity.py
```

``` shell
cd scripts/mev/opportunities/liquidation/optimism
python3 opportunity.py
```

``` shell
cd scripts/mev/opportunities/liquidation/zksync
python3 opportunity.py
```

### Downloading bytecode of MEV bots

``` shell
cd scripts/mev/code_reuse
python3 download_and_disassemble_bytecode.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

### Collecting L2 transactions sent via L1

``` shell
cd scripts/cross_layer_sandwiching/l1_analyzer
python3 L1MessageAnalyzer.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END>
```

### Linking L1 transactions to L2 transactions

``` shell
cd scripts/cross_layer_sandwiching/l2_analyzer
python3 L2MessageAnalyzer.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END> arbitrum
```

``` shell
cd scripts/cross_layer_sandwiching/l2_analyzer
python3 L2MessageAnalyzer.py <BLOCK_RANGE_START>:<BLOCK_RANGE_END> optimism
```

``` shell
cd scripts/cross_layer_sandwiching/l2_analyzer
python3 L2MessageAnalyzer.py zksync
```

### Simulating cross-layer sandwich attacks

``` shell
cd scripts/cross_layer_sandwiching/simulation
python3 arbitrum_attack_simulator.py
```

``` shell
cd scripts/cross_layer_sandwiching/simulation
python3 optimism_attack_simulator.py
```

### Testnet cross-layer sandwich attack validation

``` shell
cd scripts/cross_layer_sandwiching/testnet
python3 attacker_script_arbitrum_all_attacks.py
```

``` shell
cd scripts/cross_layer_sandwiching/testnet
python3 attacker_script_optimism_all_attacks.py
```

``` shell
cd scripts/cross_layer_sandwiching/testnet
python3 attacker_script_zksync_all_attacks.py
```

Required Solidity contracts can be found in ```scripts/cross_layer_sandwiching/testnet/contracts```.

## Comparing and analyzing extracted MEV (i.e., reproducing the results in our paper) 

Make sure Juypter notebook is running and that you have installed all Python dependencies.

Then open up http://localhost:8888 on your browser and navigate to ```analysis```.

To compare and analyze MEV volume (Section 4.1) run:

```
4_1_volume.ipynb
```

To compare and analyze MEV profits (Section 4.2) run:

```
4_2_profits.ipynb
```

To compare and analyze MEV costs (Section 4.3) run:

```
4_3_costs.ipynb
```

To compare and analyze MEV opportunities (Section 4.4) run:

```
4_4_opportunities.ipynb
```

To compare and analyze MEV competition (Section 4.5) run:

```
4_5_competition.ipynb
```

To compare and analyze MEV flash loans (Section 4.6) run:

```
4_6_flash_loans.ipynb
```

To compare and analyze MEV code reuse (Section 4.7) run:

```
4_7_code_reuse.ipynb
```

To compare and analyze cross-layer sandwiching victim inference (Section 5.3.1) run:

```
5_3_1_victim_inference.ipynb
```

To compare and analyze cross-layer sandwiching transaction inclusion delays (Section 5.3.2) run:

```
5_3_2_transaction_inclusion_delays.ipynb
```

To compare and analyze cross-layer sandwiching estimated profits (Section 5.3.3) run:

```
5_3_3_estimated_profits.ipynb
```

## Attribution
If using this repository for research, please cite as:

``` bibtex
@article{rollingintheshadows,
  author       = {Ferreira Torres, Christof and
                  Mamuti, Albin and
                  Weintraub, Ben and
                  Nita{-}Rotaru, Cristina and
                  Shinde, Shweta},
  title        = {Rolling in the Shadows: Analyzing the Extraction of {MEV} Across Layer-2 Rollups},
  booktitle    = {Proceedings of the 2024 {ACM} {SIGSAC} Conference on Computer and
                  Communications Security, {CCS} 2024, Salt Lake City, UT, USA, October
                  14-18, 2024},
  publisher    = {{ACM}},
  year         = {2024}
}
```
