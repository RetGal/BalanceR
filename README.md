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

### Auto Quote
Soll ein oder mehrere Bot Instanzen mir Auto Quote (`MM`oder `MMRange`) betrieben werden, so empfiehlt es sich, zusätzlich eine *Mayer* Instanz laufen zu lassen.

### Mayer Multiple
*mayer.py* ermittelt stündlich den BTC/USD Kurs und aktualisert damit den Tagesdurschnittskurs.
Aufgrund des Durschnittskurses der letzten 200 Tage und dem aktuellen Kurswert können die Bot Instanzen sehr genaue und aktuelle Mayer Multiples berechnen.

Vor dem erstmaligen Start ist die Konfigurationsdatei *mayer.txt* mit dem Namen der gewünschten Börse zu ergänzen.

Der Name der zu verwendenden Konfigurationsdatei kann als Parameter, ohne der Dateierweiterung (*.txt*), übergeben werden:

`./mayer.py mayer`

Fehlt der Parameter, so fragt das Script bei jedem Start nach dem Namen der Konfigurationsdatei. Diesen gilt es ohne Dateierweiterung (*.txt*) einzugeben. Wird dieser Schritt übersprungen, so wird standardmässig die Konfiguration von *mayer.txt* verwendet.

## Betrieb
### Bot Instanzen
Mit Hilfe des Watchdog-Scrpits *[osiris](https://github.com/RetGal/osiris)* lässt sich eine beliebige Anzahl Bot Instanzen überwachen.
Sollte eine Instanz nicht mehr laufen, wird sie automatisch neu gestartet. Daneben stellt der Watchdog auch sicher, dass stets genügend freier Speicher vorhanden ist.

Dazu sollte der Variable *workingDir* der absolute Pfad zum *balancer.py* Script angegeben werden, *scriptName* sollte *balancer.py* lauten.
Voraussetzung ist, dass die *balancer.py* Instanzen innerhalb von *tmux* Sessions ausgeführt werden, welche gleich heissen wie die entsprechende Konfigurationsdatei:

Wenn also eine Konfigurationsdatei beispielsweise *test1.txt* heisst, dann sollte *balancer.py test1* innerhalb einer *tmux* Session namens *test1* laufen.

Damit *osiris.sh* die *BalanceR*  Instanzen kontinuierlich überwachen kann, muss ein entsprechender *Cronjob* eingerichtet werden:

`*/5 *   *   *   *   /home/bot/balancer/osiris.sh`

Die beiden Dateien *balancer.py* und *osiris.sh* müssen vor dem ersten Start mittels `chmod +x` ausführbar gemacht werden.

### Mayer Instanz
Mit Hilfe des Watchdog-Scrpits *mayer_osiris.sh* lässt sich die zentrale *Mayer* Instanz überwachen.

Dazu sollte der Variable *workingDir* der absolute Pfad zum *mayer.py* Script angegeben werden.

Damit *mayer_osiris.sh* die *Mayer*  Instanz kontinuierlich überwachen kann, muss ein entsprechender *Cronjob* eingerichtet werden:

`*/6 *   *   *   *   /home/bot/balancer/mayer_osiris.sh`

Die beiden Dateien *mayer.py* und *mayer_osiris.sh* müssen vor dem ersten Start mittels `chmod +x` ausführbar gemacht werden.

## Troubleshooting

Jede Instanz erstellt und schreibt in eine eigene Logdatei. Diese heisst so wie die entsprechende Konfigurationsdatei, beindet sich im `log` Verzeichnis endet aber auf *.log*:

`test1.log`

Fehlt diese Datei, dann konnte *balancer.py* nicht gestartet werden.
Die nächste Anlaufstelle wäre die entsprechende *tmux* Session:

`tmux a -t test1`

## Docker

Container builden

```bash
docker build -t  retgal/balancer:latest .
```

Gebuildeten BalanceR mit der externen config test.txt starten

```bash
docker run -it -v /opt/data:/opt/data -e BALANCER_CONFIG="/opt/data/test" --name balancer_test retgal/balancer:latest
```

Oder dasselbe ohne zu builden mit dem vorgefertigten von Dockerhub: 

```bash
docker pull dockerocker/balancer
docker run -it -v /opt/data:/opt/data -e BALANCER_CONFIG="/opt/data/test" --name balancer_test dockerocker/balancer:latest
```
