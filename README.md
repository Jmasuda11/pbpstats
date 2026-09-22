# pbpstats (fork)

A package to scrape and parse NBA, WNBA and G-League play-by-play data.

This is a [fork](https://github.com/Jmasuda11/pbpstats) of [dblackrun/pbpstats](https://github.com/dblackrun/pbpstats), including native V3 game loading and evidence preparation.

# Features

* Adds lineup on floor for all events
* Adds detailed data for each possession including start time, end time, score margin, how the previous possession ended
* Shots, rebounds and assists broken down by shot zone
* Supports both stats.nba.com and data.nba.com endpoints
* Supports NBA, WNBA and G-League stats
* All stats on pbpstats.com are derived from these stats
* Fixes order of events for some common cases in which events are out of order

# Installation

Tested on Python 3.8–3.12. Install this fork directly from GitHub (Git must be installed):

```bash
pip install git+https://github.com/Jmasuda11/pbpstats.git
```

# Resources

- [Fork: loading a V3 game offline](docs/v3-game-loading.rst)
- [Fork: preparing V3 game evidence](docs/v3-evidence-preparation.rst)
- [Upstream documentation](https://pbpstats.readthedocs.io/en/latest/)

# Local Development

Using [poetry](https://python-poetry.org/) for package management. Install it first if it is not installed on your system.

`git clone https://github.com/Jmasuda11/pbpstats.git`

`cd pbpstats`

Develop using the `main` branch:
`git checkout main`

Install dependencies:

`poetry install`

Activate virtualenv:

`poetry shell`

Install pre-commit:

`pre-commit install`
