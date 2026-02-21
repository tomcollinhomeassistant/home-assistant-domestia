"""Constantes Domestia."""

DOMAIN = "domestia"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"

# Pas d'IP "perso" en défaut: chaque install est différente
DEFAULT_HOST = ""
DEFAULT_PORT = 52000
DEFAULT_SCAN_INTERVAL = 5  # secondes

# Virtuelles 57..104 (scènes) - On les garde car ce ne sont pas des modules physiques découvrables
VIRTUAL_BUTTONS: dict[int, str] = {i: f"Sortie {i}" for i in range(57, 105)}