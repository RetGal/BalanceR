# BalanceR
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=RetGal_BalanceR&metric=alert_status)](https://sonarcloud.io/dashboard?id=RetGal_BalanceR)
![Python application](https://github.com/RetGal/BalanceR/workflows/Python%20application/badge.svg)

## Voraussetzungen

*BalanceR* setzt *Python* Version 3 oder grösser voraus.
Im Kern verwendet *BalanceR* die [ccxt](https://github.com/ccxt/ccxt) Bibliothek. Diese gilt es mittels [pip](https://pypi.org/project/pip/) zu installieren:

`python -m pip install -r requirements.txt`

Sollen mehrere *BalanceR* Instanzen auf demselben Server betrieben werden, so wird die Installation von [tmux](https://github.com/tmux/tmux/wiki) empfohlen.

`apt install tmux`


## Inbetriebnahme
### Bot Instanzen
Vor dem erstmaligen Start ist die Konfigurationsdatei *config.txt* mit den gewünschten API Keys und Einstellungen zu ergänzen.
Es können mehrere config Dateien erstellt und dieselbe *balancer.py* Datei zum Start verwendet werden.

Der Name der zu verwendenden Konfigurationsdatei kann als Parameter, ohne der Dateierweiterung (*.txt*), übergeben werden:

`./balancer.py test`

Fehlt der Parameter, so fragt das Script bei jedem Start nach dem Namen der Konfigurationsdatei. Diesen gilt es ohne Dateierweiterung (*.txt*) einzugeben. Wird dieser Schritt übersprungen, wird standardmässig die Konfiguration von *config.txt* verwendet.



